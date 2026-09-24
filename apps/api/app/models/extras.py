"""memories, tool_calls, subscriptions, payments, payment_webhook_events, api_keys (docs/08)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, SoftDeleteMixin, TimestampMixin, enum_check
from app.models.files import EMBED_DIM

API_SCOPES = (
    "chat:write",
    "conversations:read",
    "conversations:write",
    "files:read",
    "files:write",
    "memories:read",
    "usage:read",
)
SUB_STATUSES = (
    "created",
    "authenticated",
    "active",
    "pending",
    "halted",
    "cancelled",
    "completed",
    "expired",
)


class Memory(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint("char_length(content) >= 3", name="content_len"),
        CheckConstraint(
            enum_check(
                "category", ("preference", "biographical", "project", "instruction", "other")
            ),
            name="category_valid",
        ),
        CheckConstraint("importance BETWEEN 1 AND 5", name="importance_range"),
        CheckConstraint(enum_check("source", ("extracted", "user_created")), name="source_valid"),
        Index(
            "ix_memories_user_updated",
            "user_id",
            text("updated_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_memories_user_hash",
            "user_id",
            "content_hash",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_memories_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default="other")
    importance: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="3")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolCall(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint(
            enum_check(
                "status", ("pending", "running", "succeeded", "failed", "timed_out", "denied")
            ),
            name="status_valid",
        ),
        CheckConstraint("iteration BETWEEN 0 AND 10", name="iteration_range"),
        Index("ix_tool_calls_user", "user_id", "created_at"),
        Index("ix_tool_calls_name", "tool_name", "created_at"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider_tool_call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    iteration: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class Subscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(enum_check("status", SUB_STATUSES), name="status_valid"),
        Index(
            "uq_subscriptions_user_live",
            "user_id",
            unique=True,
            postgresql_where=text(
                "status IN ('created','authenticated','active','pending','halted')"
            ),
        ),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    plan_key: Mapped[str] = mapped_column(
        Text, ForeignKey("plans.key", ondelete="RESTRICT"), nullable=False
    )
    razorpay_subscription_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    razorpay_customer_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="created")
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(IdMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            enum_check("status", ("created", "authorized", "captured", "failed", "refunded")),
            name="status_valid",
        ),
        CheckConstraint("amount_paise >= 0", name="amount_nonneg"),
        Index("ix_payments_user", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True
    )
    razorpay_payment_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    razorpay_invoice_id: Mapped[str | None] = mapped_column(String(64))
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64))
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str | None] = mapped_column(String(32))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentWebhookEvent(IdMixin, Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id"),
        CheckConstraint(enum_check("provider", ("razorpay",)), name="provider_valid"),
    )

    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="razorpay")
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApiKey(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(
            "scopes <@ ARRAY[" + ",".join(f"'{s}'" for s in API_SCOPES) + "]::text[]",
            name="scopes_valid",
        ),
        Index("ix_api_keys_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    key_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{chat:write,conversations:read}"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_ip: Mapped[str | None] = mapped_column(INET)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
