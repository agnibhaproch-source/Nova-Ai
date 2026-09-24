"""Append-only audit logging (docs/38 §7)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def audit(
    db: AsyncSession,
    action: str,
    *,
    actor_user_id: uuid.UUID | str | None = None,
    actor_type: str = "user",
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    reason: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Adds an audit row to the caller's transaction (committed with the domain change)."""
    db.add(
        AuditLog(
            actor_user_id=uuid.UUID(str(actor_user_id)) if actor_user_id else None,
            actor_type=actor_type,
            action=action,
            target_type=target_type,
            target_id=uuid.UUID(str(target_id)) if target_id else None,
            reason=reason,
            ip_address=ip,
            user_agent=(user_agent or "")[:512] or None,
            request_id=request_id,
            metadata_=metadata or {},
        )
    )
