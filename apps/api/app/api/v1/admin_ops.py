"""Admin operations: dashboard, usage, health, errors, billing, moderation, models, plans,
analytics, audited content access (docs/36). Roles enforced server-side on every route."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models_registry import get_registry
from app.api.deps import Principal, rate_limit, request_id, require_csrf, require_role
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode, not_found
from app.core.redis import get_redis, rkey
from app.db.session import get_db
from app.models import (
    Conversation,
    File,
    Message,
    ModerationFlag,
    Payment,
    PaymentWebhookEvent,
    Plan,
    Subscription,
    ToolCall,
    UsageDaily,
    UsageRecord,
    User,
)
from app.schemas.common import Envelope, In, ListEnvelope
from app.services import billing_service, message_service, settings_service
from app.services.audit_service import audit

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(rate_limit("admin"))])
support = require_role("support")
admin = require_role("admin")
RANGES = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}


def _since(r: str) -> datetime:
    return datetime.now(UTC) - RANGES.get(r, RANGES["7d"])


@router.get("/dashboard", operation_id="admin_dashboard")
async def dashboard(
    range: Literal["24h", "7d", "30d"] = "7d",  # noqa: A002
    db: AsyncSession = Depends(get_db),
    _p: Principal = Depends(support),
) -> Envelope[dict[str, Any]]:
    since = _since(range)

    async def one(q: Any) -> Any:
        return await db.scalar(q)

    users_total = await one(select(func.count()).select_from(User).where(User.status != "deleted"))
    new_users = await one(select(func.count()).select_from(User).where(User.created_at >= since))
    active = await one(
        select(func.count(func.distinct(Message.user_id))).where(
            Message.role == "user", Message.created_at >= since
        )
    )
    msgs = await one(
        select(func.count())
        .select_from(Message)
        .where(Message.role == "user", Message.created_at >= since)
    )
    tok = await one(
        select(func.coalesce(func.sum(UsageRecord.total_tokens), 0)).where(
            UsageRecord.created_at >= since
        )
    )
    cost = await one(
        select(func.sum(UsageRecord.estimated_cost_usd_micros)).where(
            UsageRecord.created_at >= since
        )
    )
    failed = await one(
        select(func.count())
        .select_from(Message)
        .where(Message.role == "assistant", Message.status == "failed", Message.created_at >= since)
    )
    done = await one(
        select(func.count())
        .select_from(Message)
        .where(Message.role == "assistant", Message.created_at >= since)
    )
    p95 = await one(
        select(func.percentile_cont(0.95).within_group(Message.time_to_first_token_ms)).where(
            Message.created_at >= since, Message.time_to_first_token_ms.is_not(None)
        )
    )
    subs = await one(
        select(func.count()).select_from(Subscription).where(Subscription.status == "active")
    )
    mrr = await one(
        select(func.coalesce(func.sum(Plan.price_paise), 0))
        .select_from(Subscription)
        .join(Plan, Plan.key == Subscription.plan_key)
        .where(Subscription.status == "active")
    )
    series = (
        await db.execute(
            text(
                "SELECT date_trunc(:unit, created_at) AS t, count(*) AS n FROM messages "
                "WHERE role = 'user' AND created_at >= :since GROUP BY 1 ORDER BY 1"
            ),
            {"unit": "hour" if range == "24h" else "day", "since": since},
        )
    ).all()
    top = (
        await db.execute(
            select(
                User.id,
                User.email,
                User.plan_key,
                func.sum(UsageRecord.total_tokens).label("tokens"),
                func.sum(UsageRecord.estimated_cost_usd_micros).label("cost"),
            )
            .join(UsageRecord, UsageRecord.user_id == User.id)
            .where(UsageRecord.created_at >= since)
            .group_by(User.id)
            .order_by(func.sum(UsageRecord.total_tokens).desc())
            .limit(10)
        )
    ).all()
    return Envelope(
        data={
            "users_total": users_total,
            "new_users": new_users,
            "active_users": active,
            "messages": msgs,
            "tokens": int(tok or 0),
            "estimated_cost_usd": round((cost or 0) / 1_000_000, 4) if cost is not None else None,
            "error_rate": round((failed or 0) / done, 4) if done else 0.0,
            "p95_ttft_ms": int(p95) if p95 else None,
            "active_subscriptions": subs,
            "mrr_paise": int(mrr or 0),
            "series": [{"t": r.t, "messages": r.n} for r in series],
            "top_users": [
                {
                    "id": str(r.id),
                    "email": r.email,
                    "plan_key": r.plan_key,
                    "tokens": int(r.tokens or 0),
                    "estimated_cost_usd": round((r.cost or 0) / 1_000_000, 4),
                }
                for r in top
            ],
        }
    )


@router.get("/usage", operation_id="admin_usage")
async def usage(
    days: int = Query(default=30, ge=1, le=180),
    group_by: Literal["day", "model", "kind"] = "day",
    db: AsyncSession = Depends(get_db),
    _p: Principal = Depends(support),
) -> ListEnvelope[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=days)
    col = {
        "day": func.date_trunc("day", UsageRecord.created_at),
        "model": func.coalesce(UsageRecord.model_key, ""),
        "kind": UsageRecord.kind,
    }[group_by]
    rows: Any = (
        await db.execute(
            select(
                col.label("key"),
                func.count().label("requests"),
                func.sum(UsageRecord.prompt_tokens).label("prompt"),
                func.sum(UsageRecord.completion_tokens).label("completion"),
                func.count().filter(UsageRecord.status == "error").label("errors"),
                func.sum(UsageRecord.estimated_cost_usd_micros).label("cost"),
            )
            .where(UsageRecord.created_at >= since)
            .group_by(col)
            .order_by(col)
        )
    ).all()
    return ListEnvelope(
        data=[
            {
                "key": r.key,
                "requests": r.requests,
                "prompt_tokens": int(r.prompt or 0),
                "completion_tokens": int(r.completion or 0),
                "errors": r.errors,
                "estimated_cost_usd": round((r.cost or 0) / 1_000_000, 4) if r.cost else None,
            }
            for r in rows
        ]
    )


@router.get("/conversations", operation_id="admin_conversations")
async def conversations(
    user_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    _p: Principal = Depends(support),
) -> ListEnvelope[dict[str, Any]]:
    stmt = select(Conversation).order_by(Conversation.last_message_at.desc())
    if user_id:
        stmt = stmt.where(Conversation.user_id == user_id)
    rows = (await db.execute(stmt.offset((page - 1) * 50).limit(50))).scalars().all()
    # Titles hidden by default: they can contain personal content (docs/36 §6).
    return ListEnvelope(
        data=[
            {
                "id": str(c.id),
                "user_id": str(c.user_id),
                "message_count": c.message_count,
                "model_key": c.model_key,
                "created_at": c.created_at,
                "last_message_at": c.last_message_at,
                "deleted": c.deleted_at is not None,
            }
            for c in rows
        ]
    )


@router.get("/conversations/{conversation_id}/messages", operation_id="admin_content")
async def content(
    conversation_id: uuid.UUID,
    request: Request,
    reason: str = Query(default="", max_length=500),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(admin),
) -> ListEnvelope[dict[str, Any]]:
    if len(reason.strip()) < 10:
        raise AppError(ErrorCode.REASON_REQUIRED)
    conv = await db.get(Conversation, conversation_id)
    if conv is None:
        raise not_found()
    audit(
        db,
        "admin.content.accessed",
        actor_user_id=p.uid,
        actor_type="admin",
        target_type="conversation",
        target_id=conv.id,
        reason=reason.strip(),
        request_id=request_id(request),
    )
    await db.commit()
    msgs = (
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conv.id)
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    return ListEnvelope(
        data=await message_service.serialize(db, list(msgs), with_siblings=False),
        meta={"title": conv.title, "audited": True},
    )


@router.get("/health", operation_id="admin_health")
async def health(
    db: AsyncSession = Depends(get_db), _p: Principal = Depends(support)
) -> Envelope[dict[str, Any]]:
    import time

    from app.embeddings.service import get_embeddings
    from app.files import storage

    out: dict[str, Any] = {}
    t = time.perf_counter()
    await db.scalar(text("SELECT 1"))
    out["database"] = {"status": "ok", "latency_ms": int((time.perf_counter() - t) * 1000)}
    try:
        t = time.perf_counter()
        await get_redis().ping()
        info = await get_redis().info("memory")
        out["redis"] = {
            "status": "ok",
            "latency_ms": int((time.perf_counter() - t) * 1000),
            "used_memory": info.get("used_memory_human"),
        }
    except Exception:
        out["redis"] = {"status": "down"}
    try:
        await asyncio.wait_for(storage.head("healthcheck/none"), 3)
        out["storage"] = {"status": "ok"}
    except Exception:
        out["storage"] = {"status": "down"}
    hb = await get_redis().get(rkey("worker", "heartbeat"))
    out["worker"] = {"status": "ok" if hb else "down", "last_heartbeat": hb}
    try:
        from arq.connections import ArqRedis

        from app.workers.queue import get_pool

        pool: ArqRedis = await get_pool()
        out["queue"] = {"depth": await pool.zcard("arq:queue")}
    except Exception:
        out["queue"] = {"depth": None}
    if get_settings().GROQ_KEY_MODE == "user":
        # BYOK: there is no server key to probe with; each chat verifies its own key.
        out["groq"] = {"mode": "user", "models": "verified per conversation"}
    else:
        try:
            from app.ai.groq.service import get_groq_service

            report = await asyncio.wait_for(get_groq_service().verify_models(), 10)
            out["groq"] = {"mode": "server", "models": report}
        except Exception:
            out["groq"] = {"mode": "server", "models": "unavailable"}
    out["embeddings"] = {
        "status": "configured"
        if get_embeddings().available()
        else "not_configured (full-text search only)"
    }
    stuck = await db.scalar(
        select(func.count())
        .select_from(File)
        .where(
            File.status.in_(("uploaded", "scanning", "processing")),
            File.updated_at < datetime.now(UTC) - timedelta(minutes=15),
        )
    )
    out["files_stuck"] = stuck
    return Envelope(data=out)


@router.get("/errors", operation_id="admin_errors")
async def errors(
    range: Literal["24h", "7d", "30d"] = "24h",  # noqa: A002
    db: AsyncSession = Depends(get_db),
    _p: Principal = Depends(support),
) -> Envelope[dict[str, Any]]:
    since = _since(range)

    async def grouped(model: Any, col: Any, *where: Any) -> list[dict[str, Any]]:
        rows = (
            await db.execute(
                select(col, func.count())
                .where(col.is_not(None), *where)
                .group_by(col)
                .order_by(func.count().desc())
            )
        ).all()
        return [{"code": r[0], "count": r[1]} for r in rows]

    return Envelope(
        data={
            "generation": await grouped(Message, Message.error_code, Message.created_at >= since),
            "groq": await grouped(
                UsageRecord, UsageRecord.error_code, UsageRecord.created_at >= since
            ),
            "tools": await grouped(ToolCall, ToolCall.error_code, ToolCall.created_at >= since),
            "files": await grouped(File, File.error_code, File.updated_at >= since),
            "webhooks": await grouped(
                PaymentWebhookEvent,
                PaymentWebhookEvent.processing_error,
                PaymentWebhookEvent.received_at >= since,
            ),
        }
    )


@router.get("/subscriptions", operation_id="admin_subscriptions")
async def subscriptions(
    status: str | None = None, db: AsyncSession = Depends(get_db), _p: Principal = Depends(support)
) -> ListEnvelope[dict[str, Any]]:
    stmt = select(Subscription).order_by(Subscription.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(Subscription.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return ListEnvelope(
        data=[
            {
                **(billing_service.sub_out(s) or {}),
                "user_id": str(s.user_id),
                "razorpay_subscription_id": s.razorpay_subscription_id,
            }
            for s in rows
        ]
    )


@router.get("/payments", operation_id="admin_payments")
async def payments(
    db: AsyncSession = Depends(get_db), _p: Principal = Depends(support)
) -> ListEnvelope[dict[str, Any]]:
    rows = (
        (await db.execute(select(Payment).order_by(Payment.created_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return ListEnvelope(
        data=[
            {
                "id": str(r.id),
                "user_id": str(r.user_id),
                "amount_paise": r.amount_paise,
                "status": r.status,
                "method": r.method,
                "created_at": r.created_at,
                "razorpay_payment_id": r.razorpay_payment_id,
            }
            for r in rows
        ]
    )


@router.get("/webhook-events", operation_id="admin_webhook_events")
async def webhook_events(
    failed_only: bool = False, db: AsyncSession = Depends(get_db), _p: Principal = Depends(support)
) -> ListEnvelope[dict[str, Any]]:
    stmt = select(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at.desc()).limit(200)
    if failed_only:
        stmt = stmt.where(PaymentWebhookEvent.processed_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return ListEnvelope(
        data=[
            {
                "id": str(r.id),
                "event_id": r.event_id,
                "event_type": r.event_type,
                "received_at": r.received_at,
                "processed_at": r.processed_at,
                "processing_error": r.processing_error,
            }
            for r in rows
        ]
    )


class ReasonIn(In):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/webhook-events/{event_id}/reprocess", operation_id="admin_webhook_reprocess")
async def reprocess(
    event_id: uuid.UUID,
    body: ReasonIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _a: Principal = Depends(admin),
) -> Envelope[dict[str, str]]:
    ev = await db.get(PaymentWebhookEvent, event_id)
    if ev is None:
        raise not_found()
    await billing_service._process(db, ev.event_type, ev.payload)
    ev.processed_at, ev.processing_error = datetime.now(UTC), None
    audit(
        db,
        "admin.webhook.reprocessed",
        actor_user_id=p.uid,
        actor_type="admin",
        target_type="webhook_event",
        target_id=ev.id,
        reason=body.reason,
        request_id=request_id(request),
    )
    await db.commit()
    return Envelope(data={"status": "processed"})


@router.get("/moderation/flags", operation_id="admin_flags")
async def flags(
    status: str | None = "open",
    db: AsyncSession = Depends(get_db),
    _p: Principal = Depends(support),
) -> ListEnvelope[dict[str, Any]]:
    stmt = select(ModerationFlag).order_by(ModerationFlag.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(ModerationFlag.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return ListEnvelope(
        data=[
            {
                "id": str(f.id),
                "user_id": str(f.user_id),
                "conversation_id": str(f.conversation_id) if f.conversation_id else None,
                "message_id": str(f.message_id) if f.message_id else None,
                "source": f.source,
                "category": f.category,
                "details": f.details,
                "status": f.status,
                "created_at": f.created_at,
                "resolution_note": f.resolution_note,
            }
            for f in rows
        ]
    )


class FlagPatchIn(In):
    status: Literal["reviewing", "resolved", "dismissed"]
    resolution_note: str | None = Field(default=None, max_length=2000)


@router.patch("/moderation/flags/{flag_id}", operation_id="admin_flag_update")
async def update_flag(
    flag_id: uuid.UUID,
    body: FlagPatchIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(support),
) -> Envelope[dict[str, str]]:
    f = await db.get(ModerationFlag, flag_id)
    if f is None:
        raise not_found()
    f.status, f.resolution_note = body.status, body.resolution_note
    if body.status in ("resolved", "dismissed"):
        f.resolved_by, f.resolved_at = p.uid, datetime.now(UTC)
    audit(
        db,
        "admin.moderation.updated",
        actor_user_id=p.uid,
        actor_type=p.role,
        target_type="moderation_flag",
        target_id=f.id,
        request_id=request_id(request),
        metadata={"status": body.status},
    )
    await db.commit()
    return Envelope(data={"status": f.status})


@router.get("/models", operation_id="admin_models")
async def models(
    db: AsyncSession = Depends(get_db), _p: Principal = Depends(support)
) -> ListEnvelope[dict[str, Any]]:
    disabled = set(await settings_service.get(db, "disabled_model_keys"))
    reg = get_registry()
    return ListEnvelope(
        data=[
            {
                "key": m.key,
                "display_name": m.display_name,
                "groq_model_id": m.groq_model_id,
                "enabled": m.enabled and m.key not in disabled,
                "admin_disabled": m.key in disabled,
                "context_window": m.context_window,
                "max_output_tokens": m.max_output_tokens,
                "supports_tools": m.supports_tools,
                "supports_vision": m.supports_vision,
                "pricing": m.pricing.model_dump(mode="json"),
                "plans": m.plans,
                "deprecation_date": m.deprecation_date,
            }
            for m in reg.all()
        ]
    )


class ModelToggleIn(In):
    enabled: bool
    reason: str = Field(min_length=3, max_length=500)


@router.patch("/models/{key}", operation_id="admin_model_toggle")
async def toggle_model(
    key: str,
    body: ModelToggleIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _a: Principal = Depends(admin),
) -> Envelope[dict[str, Any]]:
    reg = get_registry()
    if key not in {m.key for m in reg.all()}:
        raise not_found()
    if not body.enabled and key == reg.defaults.model_key:
        raise AppError(ErrorCode.CONFLICT, "The default model can't be disabled.")
    disabled = set(await settings_service.get(db, "disabled_model_keys"))
    disabled = disabled - {key} if body.enabled else disabled | {key}
    await settings_service.set_value(db, "disabled_model_keys", sorted(disabled), p.uid)
    reg.disabled_keys = disabled
    audit(
        db,
        "admin.model.toggled",
        actor_user_id=p.uid,
        actor_type="admin",
        reason=body.reason,
        request_id=request_id(request),
        metadata={"key": key, "enabled": body.enabled},
    )
    await db.commit()
    return Envelope(data={"key": key, "enabled": body.enabled})


@router.get("/plans", operation_id="admin_plans")
async def plans(
    db: AsyncSession = Depends(get_db), _p: Principal = Depends(support)
) -> ListEnvelope[dict[str, Any]]:
    rows = (await db.execute(select(Plan).order_by(Plan.sort_order))).scalars().all()
    return ListEnvelope(
        data=[
            {
                "key": p.key,
                "name": p.name,
                "price_paise": p.price_paise,
                "razorpay_plan_id": p.razorpay_plan_id,
                "is_active": p.is_active,
                "limits": p.limits,
            }
            for p in rows
        ]
    )


class PlanPatchIn(In):
    limits: dict[str, Any] | None = None
    is_active: bool | None = None
    description: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=3, max_length=500)


@router.patch("/plans/{key}", operation_id="admin_plan_update")
async def update_plan(
    key: str,
    body: PlanPatchIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _a: Principal = Depends(admin),
) -> Envelope[dict[str, Any]]:
    plan = await db.get(Plan, key)
    if plan is None:
        raise not_found()
    if body.limits is not None:
        unknown = set(body.limits) - set(plan.limits)
        if unknown:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                details=[{"field": "limits", "issue": f"unknown keys: {sorted(unknown)}"}],
            )
        plan.limits = {**plan.limits, **body.limits}
    if body.is_active is not None:
        plan.is_active = body.is_active
    if body.description is not None:
        plan.description = body.description
    audit(
        db,
        "admin.plan.updated",
        actor_user_id=p.uid,
        actor_type="admin",
        reason=body.reason,
        request_id=request_id(request),
        metadata={"key": key},
    )
    await db.commit()
    return Envelope(data={"key": plan.key, "limits": plan.limits, "is_active": plan.is_active})


@router.get("/analytics", operation_id="admin_analytics")
async def analytics(
    db: AsyncSession = Depends(get_db), _p: Principal = Depends(support)
) -> Envelope[dict[str, Any]]:
    since = datetime.now(UTC) - timedelta(days=30)
    funnel = (
        await db.execute(
            text(
                """
        SELECT (SELECT count(*) FROM users WHERE created_at >= :s) AS signups,
               (SELECT count(DISTINCT user_id) FROM messages WHERE role = 'user'
                  AND created_at >= :s) AS chatted,
               (SELECT count(DISTINCT m.user_id) FROM messages m JOIN users u ON u.id = m.user_id
                 WHERE m.role = 'user' AND u.created_at >= :s
                   AND m.created_at >= u.created_at + interval '1 day') AS returned
        """
            ),
            {"s": since},
        )
    ).one()
    feedback = (
        await db.execute(
            text("SELECT rating, count(*) FROM feedback WHERE created_at >= :s GROUP BY rating"),
            {"s": since},
        )
    ).all()
    tools = (
        await db.execute(
            select(ToolCall.tool_name, ToolCall.status, func.count())
            .where(ToolCall.created_at >= since)
            .group_by(ToolCall.tool_name, ToolCall.status)
        )
    ).all()
    daily = (
        await db.execute(
            select(UsageDaily.day, func.sum(UsageDaily.request_count))
            .where(UsageDaily.day >= since.date())
            .group_by(UsageDaily.day)
            .order_by(UsageDaily.day)
        )
    ).all()
    return Envelope(
        data={
            "funnel": dict(funnel._mapping),
            "feedback": {r[0]: r[1] for r in feedback},
            "tools": [{"tool": r[0], "status": r[1], "count": r[2]} for r in tools],
            "daily_requests": [{"day": r[0], "requests": int(r[1] or 0)} for r in daily],
        }
    )
