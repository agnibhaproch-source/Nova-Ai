"""Plan capability limits and usage totals (docs/35 §5–§6).

Nova enforces no usage quotas of its own (ADR 0004): the only ceiling on messages and tokens is
the Groq API key's own rate limits, which are recorded from Groq's response headers
(`app/ai/groq/ratelimits.py`). `plans.limits` still carries capability settings (models, file
sizes, output length), all set to the most generous values.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, Plan, UsageRecord


async def plan_limits(db: AsyncSession, plan_key: str) -> dict[str, Any]:
    plan = await db.get(Plan, plan_key)
    return dict(plan.limits) if plan else {}


async def usage_totals(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """What this user has sent and spent (informational only, nothing is capped)."""
    now = datetime.now(UTC)
    day_start = datetime.combine(now.date(), datetime.min.time(), UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)

    async def tokens_since(start: datetime) -> int:
        return int(
            await db.scalar(
                select(func.coalesce(func.sum(UsageRecord.total_tokens), 0)).where(
                    UsageRecord.user_id == user_id,
                    UsageRecord.created_at >= start,
                    UsageRecord.kind != "eval",
                )
            )
            or 0
        )

    messages_today = int(
        await db.scalar(
            select(func.count()).where(
                Message.user_id == user_id,
                Message.role == "user",
                Message.created_at >= day_start,
            )
        )
        or 0
    )
    return {
        "messages_today": messages_today,
        "tokens_today": await tokens_since(day_start),
        "tokens_month": await tokens_since(month_start),
    }
