from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin, enum_check

ROLES = ("user", "support", "admin")
USER_STATUSES = ("active", "suspended", "deleted")


class User(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(enum_check("role", ROLES), name="role_valid"),
        CheckConstraint(enum_check("status", USER_STATUSES), name="status_valid"),
        CheckConstraint("char_length(display_name) >= 1", name="display_name_len"),
        CheckConstraint("char_length(email) <= 254", name="email_len"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_nonneg"),
        Index(
            "uq_users_email_active",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_users_created_at", "created_at"),
    )

    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)
    avatar_storage_key: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="user")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active", index=True)
    suspended_reason: Mapped[str | None] = mapped_column(Text)
    plan_key: Mapped[str] = mapped_column(
        Text,
        ForeignKey("plans.key", ondelete="RESTRICT"),
        nullable=False,
        server_default="free",
        index=True,
    )
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
