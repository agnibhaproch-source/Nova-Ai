"""Usage records (docs/35 §2)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.groq.service import estimate_cost_micros
from app.ai.models_registry import ModelConfig
from app.ai.provider import Usage
from app.models import UsageRecord


def record(
    db: AsyncSession,
    *,
    kind: str,
    model: ModelConfig | None,
    usage: Usage | None,
    request_id: str,
    user_id: uuid.UUID | None,
    status: str = "success",
    latency_ms: int = 0,
    ttft_ms: int | None = None,
    conversation_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    error_code: str | None = None,
    provider: str = "groq",
) -> UsageRecord:
    u = usage or Usage(0, 0, 0)
    rec = UsageRecord(
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        request_id=request_id[:64],
        kind=kind,
        provider=provider,
        model_id=model.groq_model_id if model else None,
        model_key=model.key if model else None,
        prompt_tokens=u.prompt_tokens,
        completion_tokens=u.completion_tokens,
        total_tokens=u.total_tokens,
        latency_ms=latency_ms,
        time_to_first_token_ms=ttft_ms,
        status=status,
        error_code=error_code,
        estimated_cost_usd_micros=estimate_cost_micros(model, u) if model and usage else None,
    )
    db.add(rec)
    return rec
