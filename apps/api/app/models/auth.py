"""Session and email-token tables (docs/08 §2–3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String, Text, text
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, enum_check

REVOKE_REASONS = (
    "logout",
    "user_revoked",
    "password_changed",
    "admin_revoked",
    "account_suspended",
    "account_deleted",
    "expired_idle",
)


class Session(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            f"revoked_reason IS NULL OR {enum_check('revoked_reason', REVOKE_REASONS)}",
            name="revoked_reason_valid",
        ),
        Index("ix_sessions_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    device_label: Mapped[str | None] = mapped_column(String(120))


class EmailToken(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "email_tokens"
    __table_args__ = (
        CheckConstraint(
            enum_check("purpose", ("verify_email", "reset_password")), name="purpose_valid"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
