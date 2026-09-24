"""files, conversation_files, document_chunks, moderation_flags, data_exports (docs/08)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db.base import Base, CreatedAtMixin, IdMixin, SoftDeleteMixin, TimestampMixin, enum_check

FILE_STATUSES = (
    "pending_upload",
    "uploaded",
    "scanning",
    "processing",
    "ready",
    "failed",
    "rejected",
    "deleted",
)
EMBED_DIM = get_settings().EMBEDDING_DIMENSIONS or 384


class File(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint(enum_check("kind", ("document", "image", "audio")), name="kind_valid"),
        CheckConstraint(
            enum_check("purpose", ("attachment", "avatar", "voice")), name="purpose_valid"
        ),
        CheckConstraint(enum_check("status", FILE_STATUSES), name="status_valid"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index(
            "ix_files_user_created",
            "user_id",
            text("created_at DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_files_status_pending",
            "status",
            "created_at",
            postgresql_where=text(
                "status IN ('pending_upload','uploaded','scanning','processing')"
            ),
        ),
        Index("ix_files_user_sha", "user_id", "sha256"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False)
    declared_mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    detected_mime_type: Mapped[str | None] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, server_default="attachment")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending_upload")
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationFile(Base):
    __tablename__ = "conversation_files"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    attached_by_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentChunk(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("file_id", "chunk_index"),
        CheckConstraint("token_count > 0", name="tokens_positive"),
        CheckConstraint("char_end > char_start", name="char_range"),
        Index("ix_document_chunks_user_file", "user_id", "file_id"),
        Index("ix_document_chunks_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(128))
    section_title: Mapped[str | None] = mapped_column(String(300))
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    content_tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True)
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(200))


class ModerationFlag(IdMixin, TimestampMixin, Base):
    __tablename__ = "moderation_flags"
    __table_args__ = (
        CheckConstraint(
            enum_check("source", ("user_report", "automated", "admin")), name="source_valid"
        ),
        CheckConstraint(
            enum_check(
                "category",
                (
                    "abuse",
                    "spam",
                    "illegal",
                    "self_harm",
                    "harassment",
                    "rate_abuse",
                    "payment_fraud",
                    "other",
                ),
            ),
            name="category_valid",
        ),
        CheckConstraint(
            enum_check("status", ("open", "reviewing", "resolved", "dismissed")),
            name="status_valid",
        ),
        Index("ix_moderation_flags_status", "status", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[str | None] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataExport(IdMixin, TimestampMixin, Base):
    __tablename__ = "data_exports"
    __table_args__ = (
        CheckConstraint(
            enum_check("status", ("queued", "running", "ready", "failed", "expired")),
            name="status_valid",
        ),
        Index("ix_data_exports_user", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    storage_key: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    error_message: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
