"""/api/v1/models, /capabilities, /usage/* (docs/31 §4, §11)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models_registry import get_registry
from app.api.deps import Principal, rate_limit, require_scopes, require_user
from app.core.errors import AppError, ErrorCode
from app.db.session import get_db
from app.models import Conversation, UsageRecord
from app.schemas.common import Envelope, ListEnvelope, Page
from app.services import conversation_service, quota_service

router = APIRouter(tags=["models"], dependencies=[Depends(rate_limit("api_read"))])


@router.get("/models", operation_id="models_list")
async def list_models(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(require_user)
) -> ListEnvelope[dict[str, Any]]:
    reg = get_registry()
    plan_models = (await quota_service.plan_limits(db, p.plan_key)).get("models", [])
    out = []
    for m in reg.all():
        if not reg.is_enabled(m.key):
            continue
        locked = p.plan_key not in m.plans or m.key not in plan_models
        required = next((pl for pl in ("free", "plus", "pro") if pl in m.plans), None)
        out.append(
            {
                "key": m.key,
                "display_name": m.display_name,
                "description": m.description,
                "capabilities": {
                    "tools": bool(m.supports_tools),
                    "vision": m.supports_vision,
                    "json": bool(m.supports_json_mode),
                },
                "context_window": m.context_window,
                "is_default": m.key == reg.defaults.model_key,
                "locked": locked,
                "required_plan": required if locked else None,
            }
        )
    return ListEnvelope(data=out)


@router.get("/capabilities", operation_id="capabilities_get")
async def capabilities(p: Principal = Depends(require_user)) -> Envelope[dict[str, Any]]:
    from app.embeddings.service import get_embeddings
    from app.files.validation import RULES
    from app.services import voice_service
    from app.tools import engine as tool_engine

    reg = get_registry()
    vision = [m.key for m in reg.all() if reg.is_enabled(m.key) and m.supports_vision]
    tools = tool_engine.registry()
    tts = voice_service.tts_mode()
    return Envelope(
        data={
            "vision": {
                "enabled": bool(vision),
                "model_keys": vision,
                "max_images_per_message": min(
                    (reg.resolve(k).max_images_per_request or 4 for k in vision), default=0
                ),
            },
            "documents": {
                "enabled": True,
                "semantic_search": get_embeddings().available(),
                "extensions": sorted(k for k, r in RULES.items() if r.kind == "document"),
            },
            "voice_input": {"enabled": voice_service.stt_enabled()},
            "voice_output": {
                "enabled": tts != "none",
                "mode": tts,
                "voices": voice_service.voices(),
            },
            "web_search": {"enabled": "web_search" in tools},
            "code_execution": {"enabled": "code_execution" in tools},
            "video": {"enabled": False},
        }
    )


@router.get("/usage/quota", operation_id="usage_quota")
async def usage_quota(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(require_scopes("usage:read"))
) -> Envelope[dict[str, Any]]:
    return Envelope(data=await quota_service.quota_snapshot(db, p.uid, p.plan_key))


@router.get("/usage/summary", operation_id="usage_summary")
async def usage_summary(
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("usage:read")),
) -> Envelope[dict[str, Any]]:
    end = to or (datetime.now(UTC).date() + timedelta(days=1))
    start = from_ or (end - timedelta(days=30))
    if (end - start).days > 90 or end <= start:
        raise AppError(ErrorCode.VALIDATION_ERROR, details=[{"field": "from", "issue": "range"}])
    day = func.date_trunc("day", UsageRecord.created_at)
    rows = (
        await db.execute(
            select(
                day.label("day"),
                func.count().label("requests"),
                func.sum(UsageRecord.prompt_tokens).label("prompt_tokens"),
                func.sum(UsageRecord.completion_tokens).label("completion_tokens"),
                func.count().filter(UsageRecord.status == "error").label("errors"),
            )
            .where(
                UsageRecord.user_id == p.uid,
                UsageRecord.created_at >= start,
                UsageRecord.created_at < end,
            )
            .group_by(day)
            .order_by(day)
        )
    ).all()
    days = [
        {
            "day": r.day.date().isoformat(),
            "requests": r.requests,
            "prompt_tokens": int(r.prompt_tokens or 0),
            "completion_tokens": int(r.completion_tokens or 0),
            "errors": r.errors,
        }
        for r in rows
    ]
    totals = {
        k: sum(d[k] for d in days)
        for k in ("requests", "prompt_tokens", "completion_tokens", "errors")
    }
    return Envelope(data={"days": days, "totals": totals})


@router.get("/usage/records", operation_id="usage_records")
async def usage_records(
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=500),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("usage:read")),
) -> ListEnvelope[dict[str, Any]]:
    q = (
        select(UsageRecord, Conversation.title)
        .outerjoin(Conversation, Conversation.id == UsageRecord.conversation_id)
        .where(UsageRecord.user_id == p.uid)
        .order_by(UsageRecord.created_at.desc(), UsageRecord.id.desc())
    )
    if cursor:
        c = conversation_service.decode_cursor(cursor)
        q = q.where(UsageRecord.created_at < datetime.fromisoformat(c["t"]))
    rows = (await db.execute(q.limit(limit + 1))).all()
    nxt = None
    if len(rows) > limit:
        rows = rows[:limit]
        nxt = conversation_service.encode_cursor({"t": rows[-1][0].created_at})
    return ListEnvelope(
        data=[
            {
                "id": str(r.id),
                "created_at": r.created_at,
                "kind": r.kind,
                "model_key": r.model_key,
                "conversation_id": str(r.conversation_id) if r.conversation_id else None,
                "conversation_title": title,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "latency_ms": r.latency_ms,
                "status": r.status,
            }
            for r, title in rows
        ],
        page=Page(next_cursor=nxt, has_more=nxt is not None),
    )
