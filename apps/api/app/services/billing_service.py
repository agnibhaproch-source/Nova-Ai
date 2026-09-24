"""Razorpay subscriptions, verification and idempotent webhooks (docs/31 §12, docs/33 §12).

Client-reported success is never trusted alone: the signature is verified AND the subscription
is fetched from Razorpay before activation.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode, not_found
from app.models import Payment, PaymentWebhookEvent, Plan, Subscription, User
from app.services import analytics_service
from app.services.audit_service import audit

log = structlog.get_logger("app.billing")
LIVE = ("created", "authenticated", "active", "pending", "halted")
TERMINAL = ("cancelled", "completed", "expired")
ORDER = {
    s: i
    for i, s in enumerate(
        (
            "created",
            "authenticated",
            "active",
            "pending",
            "halted",
            "cancelled",
            "completed",
            "expired",
        )
    )
}


def configured() -> bool:
    s = get_settings()
    return bool(s.RAZORPAY_KEY_ID and s.RAZORPAY_KEY_SECRET)


def _client() -> Any:
    import razorpay

    s = get_settings()
    if not configured():
        raise AppError(ErrorCode.PAYMENT_PROVIDER_ERROR, "Payments aren't configured.")
    assert s.RAZORPAY_KEY_SECRET is not None
    return razorpay.Client(auth=(s.RAZORPAY_KEY_ID, s.RAZORPAY_KEY_SECRET.get_secret_value()))


async def _call(fn: Any, *args: Any) -> Any:
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args))
    except AppError:
        raise
    except Exception as e:
        log.warning("billing.provider_error", error_type=type(e).__name__)
        raise AppError(ErrorCode.PAYMENT_PROVIDER_ERROR) from e


def _ts(v: Any) -> datetime | None:
    return datetime.fromtimestamp(int(v), UTC) if v else None


def sub_out(s: Subscription | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {
        "id": str(s.id),
        "plan_key": s.plan_key,
        "status": s.status,
        "current_period_start": s.current_period_start,
        "current_period_end": s.current_period_end,
        "cancel_at_period_end": s.cancel_at_period_end,
        "created_at": s.created_at,
    }


async def plans(db: AsyncSession) -> list[Plan]:
    return list(
        (await db.execute(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)))
        .scalars()
        .all()
    )


async def current(db: AsyncSession, user_id: uuid.UUID) -> Subscription | None:
    s: Subscription | None = await db.scalar(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    return s


async def create_subscription(
    db: AsyncSession, user: User, plan_key: str, request_id: str
) -> dict[str, Any]:
    plan = await db.get(Plan, plan_key)
    if plan is None or not plan.is_active or plan.price_paise <= 0 or not plan.razorpay_plan_id:
        raise AppError(ErrorCode.PLAN_NOT_PURCHASABLE)
    live = await db.scalar(
        select(Subscription).where(Subscription.user_id == user.id, Subscription.status.in_(LIVE))
    )
    if live is not None and live.status != "created":
        raise AppError(ErrorCode.SUBSCRIPTION_EXISTS)
    if live is not None:  # abandoned checkout: replace
        live.status = "expired"
        await db.flush()
    sub_id = uuid.uuid4()
    rz = await _call(
        _client().subscription.create,
        {
            "plan_id": plan.razorpay_plan_id,
            "total_count": 120,
            "customer_notify": 1,
            "notes": {"user_id": str(user.id), "subscription_id": str(sub_id)},
        },
    )
    s = Subscription(
        id=sub_id,
        user_id=user.id,
        plan_key=plan.key,
        razorpay_subscription_id=rz["id"],
        status="created",
    )
    db.add(s)
    audit(
        db,
        "billing.subscription.created",
        actor_user_id=user.id,
        target_type="subscription",
        target_id=sub_id,
        request_id=request_id,
        metadata={"plan_key": plan.key},
    )
    await db.commit()
    return {
        "subscription_id": str(sub_id),
        "razorpay_subscription_id": rz["id"],
        "razorpay_key_id": get_settings().RAZORPAY_KEY_ID,
        "plan": plan.key,
        "prefill": {"name": user.display_name, "email": user.email},
    }


def _hmac_ok(message: str, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


async def _apply_remote(db: AsyncSession, s: Subscription, rz: dict[str, Any]) -> None:
    status = str(rz.get("status", s.status))
    if status in ORDER and (ORDER[status] >= ORDER.get(s.status, 0) or status == "active"):
        s.status = status
    s.current_period_start = _ts(rz.get("current_start")) or s.current_period_start
    s.current_period_end = _ts(rz.get("current_end")) or s.current_period_end
    s.razorpay_customer_id = rz.get("customer_id") or s.razorpay_customer_id
    if s.user_id:
        user = await db.get(User, s.user_id)
        if user is not None:
            if s.status == "active" and user.plan_key != s.plan_key:
                user.plan_key = s.plan_key
            elif (
                s.status in TERMINAL
                and user.plan_key == s.plan_key
                and (s.current_period_end is None or s.current_period_end < datetime.now(UTC))
            ):
                user.plan_key = "free"


async def verify(
    db: AsyncSession,
    user_id: uuid.UUID,
    payment_id: str,
    rz_sub_id: str,
    signature: str,
    request_id: str,
) -> Subscription:
    s = await db.scalar(
        select(Subscription).where(
            Subscription.razorpay_subscription_id == rz_sub_id, Subscription.user_id == user_id
        )
    )
    if s is None:
        raise not_found()
    secret = get_settings().RAZORPAY_KEY_SECRET
    if secret is None or not _hmac_ok(
        f"{payment_id}|{rz_sub_id}", signature, secret.get_secret_value()
    ):
        raise AppError(ErrorCode.PAYMENT_SIGNATURE_INVALID)
    rz = await _call(_client().subscription.fetch, rz_sub_id)
    was = s.status
    await _apply_remote(db, s, rz)
    audit(
        db,
        "billing.subscription.verified",
        actor_user_id=user_id,
        target_type="subscription",
        target_id=s.id,
        request_id=request_id,
        metadata={"status": s.status},
    )
    if s.status == "active" and was != "active":
        await analytics_service.track(
            db, "subscription_started", user_id=user_id, properties={"plan_key": s.plan_key}
        )
    await db.commit()
    await _refresh_sessions(db, user_id)
    return s


async def cancel(
    db: AsyncSession, user_id: uuid.UUID, at_period_end: bool, request_id: str
) -> Subscription:
    s = await db.scalar(
        select(Subscription).where(Subscription.user_id == user_id, Subscription.status.in_(LIVE))
    )
    if s is None:
        raise AppError(ErrorCode.NO_ACTIVE_SUBSCRIPTION)
    await _call(
        _client().subscription.cancel,
        s.razorpay_subscription_id,
        {"cancel_at_cycle_end": 1 if at_period_end else 0},
    )
    s.cancel_at_period_end = at_period_end
    s.cancelled_at = datetime.now(UTC)
    if not at_period_end:
        s.status = "cancelled"
    audit(
        db,
        "billing.subscription.cancelled",
        actor_user_id=user_id,
        target_type="subscription",
        target_id=s.id,
        request_id=request_id,
    )
    await db.commit()
    return s


async def _refresh_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    from app.services.auth_service import invalidate_user_sessions_cache

    await invalidate_user_sessions_cache(db, user_id)


# ------------------------------------------------------------------ webhooks
def verify_webhook(raw: bytes, signature: str) -> bool:
    secret = get_settings().RAZORPAY_WEBHOOK_SECRET
    if secret is None:
        return False
    expected = hmac.new(secret.get_secret_value().encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


async def handle_webhook(db: AsyncSession, event_id: str, payload: dict[str, Any]) -> bool:
    """Returns False for duplicates. Only forward state transitions are applied."""
    etype = str(payload.get("event", ""))
    res = await db.execute(
        insert(PaymentWebhookEvent)
        .values(
            provider="razorpay", event_id=event_id[:128], event_type=etype[:64], payload=payload
        )
        .on_conflict_do_nothing()
        .returning(PaymentWebhookEvent.id)
    )
    row_id = res.scalar()
    if row_id is None:
        await db.commit()
        return False
    try:
        await _process(db, etype, payload)
        await db.execute(
            update(PaymentWebhookEvent)
            .where(PaymentWebhookEvent.id == row_id)
            .values(processed_at=datetime.now(UTC))
        )
        await db.commit()
    except Exception as e:
        await db.rollback()
        await db.execute(
            update(PaymentWebhookEvent)
            .where(PaymentWebhookEvent.id == row_id)
            .values(processing_error=type(e).__name__)
        )
        await db.commit()
        log.exception("billing.webhook.failed", event_type=etype)
    return True


async def _process(db: AsyncSession, etype: str, payload: dict[str, Any]) -> None:
    ent = payload.get("payload", {})
    sub_ent = (ent.get("subscription") or {}).get("entity") or {}
    pay_ent = (ent.get("payment") or {}).get("entity") or {}
    sub = None
    rz_sub_id = sub_ent.get("id") or pay_ent.get("subscription_id")
    if rz_sub_id:
        sub = await db.scalar(
            select(Subscription)
            .where(Subscription.razorpay_subscription_id == rz_sub_id)
            .with_for_update()
        )
    if sub is not None and sub_ent:
        await _apply_remote(db, sub, sub_ent)
        audit(
            db,
            "billing.subscription.state_changed",
            actor_type="webhook",
            target_type="subscription",
            target_id=sub.id,
            metadata={"event": etype, "status": sub.status},
        )
    if pay_ent.get("id"):
        status = {
            "captured": "captured",
            "authorized": "authorized",
            "failed": "failed",
            "refunded": "refunded",
        }.get(str(pay_ent.get("status")), "created")
        values = {
            "user_id": sub.user_id if sub else None,
            "subscription_id": sub.id if sub else None,
            "razorpay_payment_id": pay_ent["id"],
            "razorpay_invoice_id": pay_ent.get("invoice_id"),
            "razorpay_order_id": pay_ent.get("order_id"),
            "amount_paise": int(pay_ent.get("amount") or 0),
            "currency": pay_ent.get("currency") or "INR",
            "status": status,
            "method": pay_ent.get("method"),
            "failure_reason": pay_ent.get("error_description"),
            "captured_at": datetime.now(UTC) if status == "captured" else None,
        }
        await db.execute(
            insert(Payment)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[Payment.razorpay_payment_id],
                set_={k: values[k] for k in ("status", "failure_reason", "captured_at", "method")},
            )
        )
        audit(
            db,
            "billing.payment.recorded",
            actor_type="webhook",
            target_type="payment",
            metadata={"status": status, "amount_paise": values["amount_paise"]},
        )
        if status == "failed" and sub is not None and sub.user_id:
            await analytics_service.track(
                db,
                "subscription_payment_failed",
                user_id=sub.user_id,
                properties={"plan_key": sub.plan_key},
            )


async def downgrade_halted(db: AsyncSession) -> int:
    """Plan → free after a 3-day grace for halted subscriptions (docs/31 §12)."""
    cutoff = datetime.now(UTC) - timedelta(days=3)
    subs = (
        (
            await db.execute(
                select(Subscription).where(
                    Subscription.status == "halted", Subscription.updated_at < cutoff
                )
            )
        )
        .scalars()
        .all()
    )
    n = 0
    for s in subs:
        user = await db.get(User, s.user_id) if s.user_id else None
        if user and user.plan_key == s.plan_key:
            user.plan_key = "free"
            n += 1
    await db.commit()
    return n
