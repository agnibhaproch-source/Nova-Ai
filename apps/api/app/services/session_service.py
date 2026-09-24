"""Server-side sessions: create, resolve (Redis-cached), revoke (docs/09 §5–9)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from user_agents import parse as parse_ua

from app.core.config import get_settings
from app.core.redis import get_redis, rkey
from app.core.security import new_token, sha256
from app.models import Session, User

MAX_ACTIVE_SESSIONS = 50
CACHE_TTL_S = 60


@dataclass
class SessionInfo:
    session_id: str
    user_id: str
    role: str
    status: str
    plan_key: str
    expires_at: str
    last_seen_at: str
    created_at: str


def _cache_key(token_hash: bytes) -> str:
    return rkey("session", token_hash.hex())


def device_label(ua: str | None) -> str | None:
    if not ua:
        return None
    parsed = parse_ua(ua)
    return f"{parsed.browser.family} on {parsed.os.family}"[:120]


async def create_session(
    db: AsyncSession, user: User, *, ip: str | None, user_agent: str | None
) -> tuple[Session, str]:
    token = new_token()
    now = datetime.now(UTC)
    s = Session(
        user_id=user.id,
        token_hash=sha256(token),
        expires_at=now + timedelta(days=get_settings().SESSION_TTL_DAYS),
        last_seen_at=now,
        ip_address=ip,
        user_agent=(user_agent or "")[:512] or None,
        device_label=device_label(user_agent),
    )
    db.add(s)
    await db.flush()
    active = (
        await db.execute(
            select(Session.id, Session.token_hash)
            .where(Session.user_id == user.id, Session.revoked_at.is_(None))
            .order_by(Session.created_at.desc())
            .offset(MAX_ACTIVE_SESSIONS)
        )
    ).all()
    if active:
        await revoke_many(
            db, [r.id for r in active], "expired_idle", [r.token_hash for r in active]
        )
    return s, token


async def resolve(db: AsyncSession, token: str) -> SessionInfo | None:
    h = sha256(token)
    redis = get_redis()
    try:
        cached = await redis.get(_cache_key(h))
    except Exception:
        cached = None
    if cached:
        data = json.loads(cached)
        info = SessionInfo(**{k: data[k] for k in SessionInfo.__dataclass_fields__ if k in data})
    else:
        row = (
            await db.execute(
                select(Session, User)
                .join(User, User.id == Session.user_id)
                .where(
                    Session.token_hash == h,
                    Session.revoked_at.is_(None),
                    Session.expires_at > datetime.now(UTC),
                    User.deleted_at.is_(None),
                )
            )
        ).first()
        if row is None:
            return None
        sess, user = row
        info = SessionInfo(
            session_id=str(sess.id),
            user_id=str(user.id),
            role=user.role,
            status=user.status,
            plan_key=user.plan_key,
            expires_at=sess.expires_at.isoformat(),
            last_seen_at=sess.last_seen_at.isoformat(),
            created_at=user.created_at.isoformat(),
        )
        try:
            await redis.set(_cache_key(h), json.dumps(info.__dict__), ex=CACHE_TTL_S)
        except Exception:
            pass
    now = datetime.now(UTC)
    if datetime.fromisoformat(info.expires_at) <= now:
        return None
    idle = (
        timedelta(hours=12)
        if info.role in ("admin", "support")
        else timedelta(days=get_settings().SESSION_IDLE_TIMEOUT_DAYS)
    )
    if datetime.fromisoformat(info.last_seen_at) < now - idle:
        await revoke_many(db, [uuid.UUID(info.session_id)], "expired_idle", [h])
        await db.commit()
        return None
    if datetime.fromisoformat(info.last_seen_at) < now - timedelta(minutes=5):
        await db.execute(
            update(Session).where(Session.id == uuid.UUID(info.session_id)).values(last_seen_at=now)
        )
        await db.commit()
        await invalidate_cache([h])
    return info


async def invalidate_cache(token_hashes: list[bytes]) -> None:
    if not token_hashes:
        return
    try:
        await get_redis().delete(*[_cache_key(h) for h in token_hashes])
    except Exception:
        pass


async def revoke_many(
    db: AsyncSession, ids: list[uuid.UUID], reason: str, token_hashes: list[bytes] | None = None
) -> int:
    if not ids:
        return 0
    rows = (
        (
            await db.execute(
                update(Session)
                .where(Session.id.in_(ids), Session.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
                .returning(Session.token_hash)
            )
        )
        .scalars()
        .all()
    )
    await invalidate_cache(list(rows) + list(token_hashes or []))
    return len(rows)


async def revoke_all_for_user(
    db: AsyncSession, user_id: uuid.UUID, reason: str, *, except_session_id: uuid.UUID | None = None
) -> int:
    q = select(Session.id).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    if except_session_id:
        q = q.where(Session.id != except_session_id)
    ids = list((await db.execute(q)).scalars().all())
    return await revoke_many(db, ids, reason)


async def list_active(db: AsyncSession, user_id: uuid.UUID) -> list[Session]:
    return list(
        (
            await db.execute(
                select(Session)
                .where(
                    Session.user_id == user_id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > datetime.now(UTC),
                )
                .order_by(Session.last_seen_at.desc())
            )
        )
        .scalars()
        .all()
    )
