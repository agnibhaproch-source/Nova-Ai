"""/billing/* and /webhooks/razorpay (docs/31 §12)."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, rate_limit, request_id, require_csrf, require_user
from app.core.errors import AppError, ErrorCode
from app.db.session import get_db
from app.models import Payment, User
from app.schemas.common import Envelope, In, ListEnvelope
from app.services import billing_service

router = APIRouter(tags=["billing"])


def _session(p: Principal) -> None:
    if p.auth_method != "session":
        raise AppError(ErrorCode.FORBIDDEN)


@router.get("/billing/plans", operation_id="billing_plans")
async def plans(
    response: Response, db: AsyncSession = Depends(get_db)
) -> ListEnvelope[dict[str, Any]]:
    response.headers["Cache-Control"] = "public, max-age=300"
    rows = await billing_service.plans(db)
    return ListEnvelope(
        data=[
            {
                "key": p.key,
                "name": p.name,
                "description": p.description,
                "price_paise": p.price_paise,
                "currency": p.currency,
                "purchasable": p.price_paise > 0
                and bool(p.razorpay_plan_id)
                and billing_service.configured(),
                "limits_summary": {
                    k: p.limits.get(k)
                    for k in (
                        "messages_per_day",
                        "monthly_token_quota",
                        "max_document_mb",
                        "storage_mb",
                        "web_search_per_day",
                        "code_executions_per_day",
                        "voice_minutes_per_day",
                        "api_access",
                    )
                },
            }
            for p in rows
        ],
        meta={"payments_enabled": billing_service.configured()},
    )


@router.get("/billing/subscription", operation_id="billing_subscription")
async def subscription(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(require_user)
) -> Envelope[dict[str, Any] | None]:
    _session(p)
    return Envelope(data=billing_service.sub_out(await billing_service.current(db, p.uid)))


class CreateSubIn(In):
    plan_key: Literal["plus", "pro"]


@router.post(
    "/billing/subscriptions",
    status_code=201,
    operation_id="billing_create",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def create(
    body: CreateSubIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Envelope[dict[str, Any]]:
    _session(p)
    user = await db.get(User, p.uid)
    assert user is not None
    return Envelope(
        data=await billing_service.create_subscription(db, user, body.plan_key, request_id(request))
    )


class VerifyIn(In):
    razorpay_payment_id: str = Field(min_length=3, max_length=64)
    razorpay_subscription_id: str = Field(min_length=3, max_length=64)
    razorpay_signature: str = Field(min_length=10, max_length=256)


@router.post(
    "/billing/subscriptions/verify",
    operation_id="billing_verify",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def verify(
    body: VerifyIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Envelope[dict[str, Any] | None]:
    _session(p)
    s = await billing_service.verify(
        db,
        p.uid,
        body.razorpay_payment_id,
        body.razorpay_subscription_id,
        body.razorpay_signature,
        request_id(request),
    )
    return Envelope(data=billing_service.sub_out(s))


class CancelIn(In):
    at_period_end: bool = True


@router.post(
    "/billing/subscription/cancel",
    operation_id="billing_cancel",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def cancel(
    body: CancelIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Envelope[dict[str, Any] | None]:
    _session(p)
    s = await billing_service.cancel(db, p.uid, body.at_period_end, request_id(request))
    return Envelope(data=billing_service.sub_out(s))


@router.get("/billing/payments", operation_id="billing_payments")
async def payments(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(require_user)
) -> ListEnvelope[dict[str, Any]]:
    _session(p)
    rows = (
        (
            await db.execute(
                select(Payment)
                .where(Payment.user_id == p.uid)
                .order_by(Payment.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return ListEnvelope(
        data=[
            {
                "id": str(r.id),
                "amount_paise": r.amount_paise,
                "currency": r.currency,
                "status": r.status,
                "method": r.method,
                "created_at": r.created_at,
                "razorpay_invoice_id": r.razorpay_invoice_id,
            }
            for r in rows
        ]
    )


@router.post(
    "/webhooks/razorpay",
    operation_id="webhooks_razorpay",
    dependencies=[Depends(rate_limit("webhook_razorpay"))],
)
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    raw = await request.body()
    if not billing_service.verify_webhook(raw, request.headers.get("x-razorpay-signature", "")):
        return Response(status_code=400)
    try:
        payload = json.loads(raw)
    except ValueError:
        return Response(status_code=400)
    event_id = request.headers.get("x-razorpay-event-id") or str(
        uuid.uuid5(uuid.NAMESPACE_OID, raw.decode(errors="replace"))
    )
    await billing_service.handle_webhook(db, event_id, payload)
    return Response(status_code=200)
