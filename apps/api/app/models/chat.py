"""Conversations, messages, message parts, feedback (docs/08 §6–8, §19)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, SoftDeleteMixin, TimestampMixin, enum_check

MESSAGE_ROLES = ("system", "user", "assistant", "tool")
MESSAGE_STATUSES = ("pending", "streaming", "completed", "cancelled", "failed")
FINISH_REASONS = ("stop", "length", "tool_calls", "cancelled", "error", "content_filter")
PART_TYPES = ("text", "image", "file", "citation", "tool_call", "tool_result", "code")
FEEDBACK_REASONS = (
    "inaccurate",
    "not_helpful",
    "harmful",
    "incomplete",
    "wrong_citation",
    "too_long",
    "too_short",
    "other",
)


class Conversation(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("char_length(title) >= 1", name="title_len"),
        CheckConstraint(
            enum_check("title_source", ("default", "generated", "user")), name="title_source_valid"
        ),
        CheckConstraint("message_count >= 0", name="message_count_nonneg"),
        CheckConstraint("summary_token_count >= 0", name="summary_tokens_nonneg"),
        Index(
            "ix_conversations_user_active",
            "user_id",
            text("pinned_at DESC NULLS LAST"),
            text("last_message_at DESC"),
            postgresql_where=text("deleted_at IS NULL AND archived_at IS NULL"),
        ),
        Index(
            "ix_conversations_user_archived",
            "user_id",
            text("archived_at DESC"),
            postgresql_where=text("deleted_at IS NULL AND archived_at IS NOT NULL"),
        ),
        Index(
            "ix_conversations_user_deleted",
            "user_id",
            text("deleted_at DESC"),
            postgresql_where=text("deleted_at IS NOT NULL"),
        ),
        Index(
            "ix_conversations_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default="New chat")
    title_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    model_key: Mapped[str] = mapped_column(Text, nullable=False)
    current_leaf_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "messages.id",
            ondelete="SET NULL",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
    )
    summary: Mapped[str | None] = mapped_column(Text)
    summary_through_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL", use_alter=True)
    )
    summary_token_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class Message(IdMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(enum_check("role", MESSAGE_ROLES), name="role_valid"),
        CheckConstraint(enum_check("status", MESSAGE_STATUSES), name="status_valid"),
        CheckConstraint(
            f"finish_reason IS NULL OR {enum_check('finish_reason', FINISH_REASONS)}",
            name="finish_reason_valid",
        ),
        CheckConstraint("sibling_index >= 0", name="sibling_index_nonneg"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_parent", "parent_message_id", "sibling_index"),
        Index("ix_messages_user", "user_id", "created_at"),
        Index("ix_messages_content_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_messages_status_streaming",
            "updated_at",
            postgresql_where=text("status IN ('pending','streaming')"),
        ),
        Index(
            "uq_messages_conversation_idempotency",
            "conversation_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="completed")
    content_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    content_tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', left(content_text, 100000))", persisted=True)
    )
    model_key: Mapped[str | None] = mapped_column(Text)
    groq_model_id: Mapped[str | None] = mapped_column(Text)
    finish_reason: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    sibling_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    time_to_first_token_ms: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessagePart(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "message_parts"
    __table_args__ = (
        UniqueConstraint("message_id", "position"),
        CheckConstraint(enum_check("type", PART_TYPES), name="type_valid"),
        CheckConstraint("position >= 0", name="position_nonneg"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    text_content: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # FKs created by migrations 0008 / 0012 (after their target tables exist).
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="SET NULL", use_alter=True),
        index=True,
    )
    tool_call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tool_calls.id", ondelete="SET NULL", use_alter=True)
    )


class Feedback(IdMixin, TimestampMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "message_id"),
        CheckConstraint(enum_check("rating", ("up", "down")), name="rating_valid"),
        CheckConstraint(
            "reasons <@ ARRAY[" + ",".join(f"'{r}'" for r in FEEDBACK_REASONS) + "]::text[]",
            name="reasons_valid",
        ),
        CheckConstraint("char_length(comment) <= 2000", name="comment_len"),
        Index("ix_feedback_created_at", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
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
    rating: Mapped[str] = mapped_column(Text, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    comment: Mapped[str | None] = mapped_column(Text)
