"""Signup, login, logout and password reset (docs/09)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.redis import get_redis, rkey
from app.core.security import (
    hash_password,
    needs_rehash,
    new_token,
    password_policy_violation,
    sha256,
    verify_password,
)
from app.models import EmailToken, Session, User, UserPreferences
from app.services import session_service, settings_service
from app.services.audit_service import audit
from app.workers.queue import enqueue

log = structlog.get_logger()
LOCK_THRESHOLD = 10
LOCK_MINUTES = 15
DISPOSABLE_DOMAINS = frozenset(
    {
        "mailinator.com",
        "guerrillamail.com",
        "10minutemail.com",
        "tempmail.com",
        "yopmail.com",
        "trashmail.com",
        "sharklasers.com",
        "getnada.com",
        "dispostable.com",
        "maildrop.cc",
    }
)


@dataclass
class ClientCtx:
    ip: str | None
    user_agent: str | None
    request_id: str


@dataclass
class AuthResult:
    user: User
    session: Session
    token: str


async def _issue_email_token(db: AsyncSession, user: User, purpose: str) -> str:
    await db.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == purpose,
            EmailToken.consumed_at.is_(None),
        )
        .values(consumed_at=func.now())
    )
    token = new_token()
    ttl = timedelta(minutes=60)
    db.add(
        EmailToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=sha256(token),
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    return token


def _link(path: str, token: str) -> str:
    return f"{get_settings().APP_URL}/{path}?token={token}"


async def signup(
    db: AsyncSession, email: str, password: str, display_name: str, ctx: ClientCtx
) -> AuthResult:
    email = email.strip()
    if not await settings_service.get(db, "signups_enabled"):
        raise AppError(ErrorCode.SIGNUPS_DISABLED)
    domain = email.rsplit("@", 1)[-1].lower()
    if await settings_service.get(db, "block_disposable_emails") and domain in DISPOSABLE_DOMAINS:
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                {
                    "field": "email",
                    "issue": "disposable_email",
                    "message": "Use a permanent email address.",
                }
            ],
        )
    if violation := password_policy_violation(password, email):
        raise AppError(ErrorCode.PASSWORD_POLICY, violation)
    existing = await db.scalar(
        select(User.id).where(User.email == email, User.deleted_at.is_(None))
    )
    if existing:
        raise AppError(ErrorCode.EMAIL_ALREADY_REGISTERED)

    role = "user"
    bootstrap = get_settings().ADMIN_BOOTSTRAP_EMAIL
    if bootstrap and bootstrap.lower() == email.lower():
        has_admin = await db.scalar(select(User.id).where(User.role == "admin").limit(1))
        if not has_admin:
            role = "admin"
    user = User(
        email=email,
        password_hash=await hash_password(password),
        display_name=display_name.strip(),
        role=role,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as e:
        raise AppError(ErrorCode.EMAIL_ALREADY_REGISTERED) from e
    db.add(UserPreferences(user_id=user.id))
    session, token = await session_service.create_session(
        db, user, ip=ctx.ip, user_agent=ctx.user_agent
    )
    audit(
        db,
        "auth.signup",
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
        ip=ctx.ip,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
    )
    if role == "admin":
        audit(
            db,
            "admin.bootstrap",
            actor_user_id=user.id,
            actor_type="system",
            target_type="user",
            target_id=user.id,
            request_id=ctx.request_id,
        )
    await db.commit()
    return AuthResult(user, session, token)


async def login(db: AsyncSession, email: str, password: str, ctx: ClientCtx) -> AuthResult:
    user = await db.scalar(
        select(User).where(User.email == email.strip(), User.deleted_at.is_(None))
    )
    now = datetime.now(UTC)
    if user and user.locked_until and user.locked_until > now:
        raise AppError(
            ErrorCode.ACCOUNT_LOCKED, retry_after=int((user.locked_until - now).total_seconds()) + 1
        )
    ok = await verify_password(password, user.password_hash if user else None)
    if not user or not ok:
        if user:
            await _record_failed_login(db, user, ctx)
        raise AppError(ErrorCode.INVALID_CREDENTIALS)
    if user.status == "suspended":
        raise AppError(ErrorCode.ACCOUNT_SUSPENDED)
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = await hash_password(password)
    session, token = await session_service.create_session(
        db, user, ip=ctx.ip, user_agent=ctx.user_agent
    )
    audit(
        db,
        "auth.login.succeeded",
        actor_user_id=user.id,
        ip=ctx.ip,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
    )
    await db.commit()
    try:
        await get_redis().delete(rkey("loginfail", user.id))
    except Exception:
        pass
    return AuthResult(user, session, token)


async def _record_failed_login(db: AsyncSession, user: User, ctx: ClientCtx) -> None:
    fails = 1
    try:
        key = rkey("loginfail", user.id)
        fails = int(await get_redis().incr(key))
        await get_redis().expire(key, LOCK_MINUTES * 60)
    except Exception:
        fails = user.failed_login_count + 1
    user.failed_login_count = fails
    if fails >= LOCK_THRESHOLD:
        user.locked_until = datetime.now(UTC) + timedelta(minutes=LOCK_MINUTES)
        audit(db, "auth.lockout", actor_user_id=user.id, ip=ctx.ip, request_id=ctx.request_id)
    audit(
        db,
        "auth.login.failed",
        actor_user_id=user.id,
        ip=ctx.ip,
        user_agent=ctx.user_agent,
        request_id=ctx.request_id,
        metadata={"reason": "bad_password"},
    )
    await db.commit()


async def logout(db: AsyncSession, session_id: str, user_id: uuid.UUID, ctx: ClientCtx) -> None:
    await session_service.revoke_many(db, [uuid.UUID(session_id)], "logout")
    audit(db, "auth.logout", actor_user_id=user_id, ip=ctx.ip, request_id=ctx.request_id)
    await db.commit()


async def _consume_token(db: AsyncSession, token: str, purpose: str) -> EmailToken:
    row = await db.scalar(
        select(EmailToken)
        .where(
            EmailToken.token_hash == sha256(token),
            EmailToken.purpose == purpose,
            EmailToken.consumed_at.is_(None),
            EmailToken.expires_at > func.now(),
        )
        .with_for_update()
    )
    if row is None:
        raise AppError(ErrorCode.TOKEN_INVALID)
    row.consumed_at = datetime.now(UTC)
    return row


async def forgot_password(db: AsyncSession, email: str, ctx: ClientCtx) -> None:
    user = await db.scalar(
        select(User).where(
            User.email == email.strip(), User.deleted_at.is_(None), User.status == "active"
        )
    )
    if user is None:
        return
    token = await _issue_email_token(db, user, "reset_password")
    audit(
        db,
        "auth.password.reset_requested",
        actor_user_id=user.id,
        ip=ctx.ip,
        request_id=ctx.request_id,
    )
    await db.commit()
    await enqueue(
        "send_email",
        to=user.email,
        template="reset_password",
        params={"name": user.display_name, "link": _link("reset-password", token)},
    )


async def reset_password(db: AsyncSession, token: str, new_password: str, ctx: ClientCtx) -> None:
    row = await _consume_token(db, token, "reset_password")
    user = await db.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        raise AppError(ErrorCode.TOKEN_INVALID)
    if violation := password_policy_violation(new_password, user.email):
        raise AppError(ErrorCode.PASSWORD_POLICY, violation)
    user.password_hash = await hash_password(new_password)
    user.password_changed_at = datetime.now(UTC)
    user.failed_login_count = 0
    user.locked_until = None
    await session_service.revoke_all_for_user(db, user.id, "password_changed")
    audit(db, "auth.password.reset", actor_user_id=user.id, ip=ctx.ip, request_id=ctx.request_id)
    await db.commit()


async def change_password(
    db: AsyncSession, user_id: uuid.UUID, session_id: str, current: str, new: str, ctx: ClientCtx
) -> None:
    user = await db.get(User, user_id)
    if user is None or not await verify_password(current, user.password_hash):
        raise AppError(ErrorCode.INVALID_CREDENTIALS)
    if violation := password_policy_violation(new, user.email):
        raise AppError(ErrorCode.PASSWORD_POLICY, violation)
    user.password_hash = await hash_password(new)
    user.password_changed_at = datetime.now(UTC)
    await session_service.revoke_all_for_user(
        db, user.id, "password_changed", except_session_id=uuid.UUID(session_id)
    )
    audit(db, "auth.password.changed", actor_user_id=user.id, ip=ctx.ip, request_id=ctx.request_id)
    await db.commit()


async def _invalidate_user_sessions_cache(db: AsyncSession, user_id: uuid.UUID) -> None:
    hashes = (
        (
            await db.execute(
                select(Session.token_hash).where(
                    Session.user_id == user_id, Session.revoked_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    await session_service.invalidate_cache(list(hashes))


invalidate_user_sessions_cache = _invalidate_user_sessions_cache
