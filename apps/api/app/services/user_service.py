"""Profile, preferences, onboarding, sessions management, account deletion (docs/10)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, not_found
from app.core.security import verify_password
from app.models import Session, User, UserPreferences
from app.services import session_service
from app.services.audit_service import audit
from app.workers.queue import enqueue


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise AppError(ErrorCode.AUTH_REQUIRED)
    return user


async def update_profile(db: AsyncSession, user_id: uuid.UUID, fields: dict[str, Any]) -> User:
    user = await get_user(db, user_id)
    if fields.get("display_name"):
        user.display_name = fields["display_name"]
    await db.commit()
    return user


async def get_preferences(db: AsyncSession, user_id: uuid.UUID) -> UserPreferences:
    prefs = await db.get(UserPreferences, user_id)
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)
    return prefs


async def update_preferences(
    db: AsyncSession, user_id: uuid.UUID, fields: dict[str, Any], *, allowed_models: set[str]
) -> UserPreferences:
    prefs = await get_preferences(db, user_id)
    if fields.get("default_model_key") is not None and fields["default_model_key"] not in (
        allowed_models
    ):
        raise AppError(ErrorCode.MODEL_NOT_AVAILABLE)
    for k, v in fields.items():
        setattr(prefs, k, v)
    await db.commit()
    await db.refresh(prefs)
    return prefs


async def complete_onboarding(db: AsyncSession, user_id: uuid.UUID, fields: dict[str, Any]) -> User:
    user = await get_user(db, user_id)
    prefs = await get_preferences(db, user_id)
    if fields.get("custom_instructions") is not None:
        prefs.custom_instructions = fields["custom_instructions"] or None
    if fields.get("memory_enabled") is not None:
        prefs.memory_enabled = fields["memory_enabled"]
    user.onboarding_completed_at = user.onboarding_completed_at or datetime.now(UTC)
    await db.commit()
    return user


async def revoke_session(
    db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID, request_id: str
) -> None:
    s = await db.get(Session, session_id)
    if s is None or s.user_id != user_id or s.revoked_at is not None:
        raise not_found()
    await session_service.revoke_many(db, [s.id], "user_revoked")
    audit(
        db,
        "auth.session.revoked",
        actor_user_id=user_id,
        target_type="session",
        target_id=s.id,
        request_id=request_id,
    )
    await db.commit()


async def revoke_other_sessions(
    db: AsyncSession, user_id: uuid.UUID, current: str, request_id: str
) -> int:
    n = await session_service.revoke_all_for_user(
        db, user_id, "user_revoked", except_session_id=uuid.UUID(current)
    )
    audit(
        db,
        "auth.sessions.revoked_others",
        actor_user_id=user_id,
        request_id=request_id,
        metadata={"revoked_count": n},
    )
    await db.commit()
    return n


async def delete_account(
    db: AsyncSession, user_id: uuid.UUID, password: str, confirmation: str, request_id: str
) -> None:
    if confirmation != "DELETE":
        raise AppError(ErrorCode.CONFIRMATION_REQUIRED)
    user = await get_user(db, user_id)
    if not await verify_password(password, user.password_hash):
        raise AppError(ErrorCode.INVALID_CREDENTIALS)
    from app.services import api_key_service

    await api_key_service.revoke_all(db, user.id)
    user.status = "deleted"
    user.deleted_at = datetime.now(UTC)
    await session_service.revoke_all_for_user(db, user.id, "account_deleted")
    audit(
        db,
        "user.deleted",
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
        request_id=request_id,
    )
    await db.commit()
    await enqueue("purge_user", str(user.id), _job_id=f"purge_user:{user.id}")


async def list_users_admin(
    db: AsyncSession, *, q: str | None, status: str | None, page: int, page_size: int
) -> tuple[list[User], int]:
    stmt = select(User).where(User.status != "deleted")
    if q:
        like = f"%{q}%"
        conds: list[ColumnElement[bool]] = [
            User.email.ilike(like),
            User.display_name.ilike(like),
        ]
        try:
            conds.append(User.id == uuid.UUID(q))
        except ValueError:
            pass
        stmt = stmt.where(or_(*conds))
    if status:
        stmt = stmt.where(User.status == status)
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = (
        (
            await db.execute(
                stmt.order_by(User.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), min(total, 10_000)


async def admin_update_user(
    db: AsyncSession,
    actor: uuid.UUID,
    target_id: uuid.UUID,
    fields: dict[str, Any],
    reason: str,
    request_id: str,
) -> User:
    if actor == target_id and ("role" in fields or "status" in fields):
        raise AppError(ErrorCode.CANNOT_MODIFY_SELF)
    user = await db.get(User, target_id)
    if user is None or user.status == "deleted":
        raise not_found()
    if "status" in fields and fields["status"] != user.status:
        user.status = fields["status"]
        if user.status == "suspended":
            user.suspended_reason = fields.get("suspended_reason") or reason
            await session_service.revoke_all_for_user(db, user.id, "account_suspended")
            audit(
                db,
                "admin.user.suspended",
                actor_user_id=actor,
                actor_type="admin",
                target_type="user",
                target_id=user.id,
                reason=reason,
                request_id=request_id,
            )
        else:
            user.suspended_reason = None
            audit(
                db,
                "admin.user.unsuspended",
                actor_user_id=actor,
                actor_type="admin",
                target_type="user",
                target_id=user.id,
                reason=reason,
                request_id=request_id,
            )
    if "role" in fields and fields["role"] != user.role:
        if user.role == "admin":
            admins = await db.scalar(
                select(func.count()).where(User.role == "admin", User.status == "active")
            )
            if (admins or 0) <= 1:
                raise AppError(ErrorCode.CONFLICT, "At least one active admin must remain.")
        audit(
            db,
            "admin.user.role_changed",
            actor_user_id=actor,
            actor_type="admin",
            target_type="user",
            target_id=user.id,
            reason=reason,
            request_id=request_id,
            metadata={"from": user.role, "to": fields["role"]},
        )
        user.role = fields["role"]
    if "plan_key" in fields and fields["plan_key"] != user.plan_key:
        audit(
            db,
            "admin.user.plan_overridden",
            actor_user_id=actor,
            actor_type="admin",
            target_type="user",
            target_id=user.id,
            reason=reason,
            request_id=request_id,
            metadata={"from": user.plan_key, "to": fields["plan_key"]},
        )
        user.plan_key = fields["plan_key"]
    await db.commit()
    from app.services.auth_service import invalidate_user_sessions_cache

    await invalidate_user_sessions_cache(db, user.id)
    return user
