"""usage_records and usage_daily (docs/08 §14–15)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, enum_check

USAGE_KINDS = (
    "chat",
    "title",
    "summary",
    "memory_extraction",
    "embedding",
    "stt",
    "tts",
    "web_search",
    "code_execution",
    "eval",
)


class UsageRecord(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        CheckConstraint(enum_check("kind", USAGE_KINDS), name="kind_valid"),
        CheckConstraint(
            enum_check("provider", ("groq", "embeddings", "search", "sandbox")),
            name="provider_valid",
        ),
        CheckConstraint(
            enum_check("status", ("success", "error", "cancelled")), name="status_valid"
        ),
        Index("ix_usage_records_user_created", "user_id", "created_at"),
        Index("ix_usage_records_created_at", "created_at"),
        Index("ix_usage_records_kind_created", "kind", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # FK to api_keys added in migration 0014 (docs/08 §27)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL", use_alter=True)
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(200))
    model_key: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    audio_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    characters: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    time_to_first_token_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    estimated_cost_usd_micros: Mapped[int | None] = mapped_column(BigInteger)


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    __table_args__ = (Index("ix_usage_daily_day_kind", "day", "kind"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    model_key: Mapped[str] = mapped_column(String(64), primary_key=True, server_default="")
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    prompt_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    estimated_cost_usd_micros: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
