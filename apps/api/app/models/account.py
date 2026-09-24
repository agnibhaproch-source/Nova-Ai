"""Preferences, plans, audit logs, system settings, analytics events (docs/08 §4,5,21–23)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, IdMixin, TimestampMixin, enum_check

PLAN_KEYS = ("free", "plus", "pro")


class UserPreferences(TimestampMixin, Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint(enum_check("theme", ("system", "light", "dark")), name="theme_valid"),
        CheckConstraint("char_length(custom_instructions) <= 1500", name="custom_instructions_len"),
        CheckConstraint("char_length(about_user) <= 1500", name="about_user_len"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(Text, nullable=False, server_default="system")
    default_model_key: Mapped[str | None] = mapped_column(Text)
    custom_instructions: Mapped[str | None] = mapped_column(Text)
    about_user: Mapped[str | None] = mapped_column(Text)
    memory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    web_search_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    code_execution_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    send_with_enter: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, server_default="en")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="UTC")
    tts_voice: Mapped[str | None] = mapped_column(String(64))
    analytics_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class Plan(TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint(enum_check("key", PLAN_KEYS), name="key_valid"),
        CheckConstraint("price_paise >= 0", name="price_nonneg"),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    price_paise: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    razorpay_plan_id: Mapped[str | None] = mapped_column(Text, unique=True)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")


class AuditLog(IdMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            enum_check("actor_type", ("user", "admin", "support", "system", "api_key", "webhook")),
            name="actor_type_valid",
        ),
        Index("ix_audit_logs_actor", "actor_user_id", "created_at"),
        Index("ix_audit_logs_action", "action", "created_at"),
        Index("ix_audit_logs_target", "target_type", "target_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32))
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AnalyticsEvent(IdMixin, Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        CheckConstraint(enum_check("source", ("web", "api", "worker")), name="source_valid"),
        Index("ix_analytics_events_name", "event_name", "occurred_at"),
        Index("ix_analytics_events_user", "user_id", "occurred_at"),
    )

    event_name: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    anonymous_id: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    properties: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
