"""First-party product analytics with an allow-list and no content (docs/37)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnalyticsEvent, UserPreferences

# event -> allowed property keys. Client-sendable events are marked with CLIENT_EVENTS.
EVENTS: dict[str, set[str]] = {
    "page_viewed": {"path_template", "referrer_domain", "device_type"},
    "signup": {"method", "anonymous_id"},
    "login": {"method"},
    "onboarding_completed": {"use_cases", "memory_enabled", "skipped"},
    "chat_created": {"model_key", "source"},
    "message_sent": {
        "model_key",
        "has_attachments",
        "is_edit",
        "is_regenerate",
        "source",
        "char_count_bucket",
    },
    "message_completed": {
        "model_key",
        "status",
        "finish_reason",
        "ttft_ms",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "tool_count",
        "citation_count",
        "used_rag",
        "used_memory",
    },
    "generation_stopped": {"model_key", "tokens_before_stop"},
    "feedback_given": {"rating", "reasons"},
    "search_performed": {"result_count_bucket"},
    "upgrade_clicked": {"from_plan", "location"},
}
CLIENT_EVENTS = {"page_viewed", "search_performed", "upgrade_clicked", "onboarding_completed"}


def char_bucket(n: int) -> str:
    return "<100" if n < 100 else "100-500" if n < 500 else "500-2k" if n < 2000 else ">2k"


async def track(
    db: AsyncSession,
    name: str,
    *,
    user_id: uuid.UUID | None,
    properties: dict[str, Any] | None = None,
    anonymous_id: str | None = None,
    source: str = "api",
    occurred_at: datetime | None = None,
    client: bool = False,
) -> bool:
    """Adds an event to the session (caller commits). Returns False when dropped."""
    allowed = EVENTS.get(name)
    if allowed is None or (client and name not in CLIENT_EVENTS):
        return False
    if user_id is not None:
        prefs = await db.get(UserPreferences, user_id)
        if prefs is not None and prefs.analytics_opt_out:
            return False
    props = {
        k: v for k, v in (properties or {}).items() if k in allowed and not isinstance(v, dict)
    }
    db.add(
        AnalyticsEvent(
            event_name=name,
            user_id=user_id,
            anonymous_id=anonymous_id,
            source=source,
            properties=props,
            occurred_at=occurred_at or datetime.now(UTC),
        )
    )
    return True
