"""Personal API keys: shown once, HMAC-hashed, scoped, revocable (docs/10 §7, docs/09 §12)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, not_found
from app.core.redis import get_redis, rkey
from app.core.security import hmac_sha256, new_api_key
from app.models import ApiKey, User
from app.models.extras import API_SCOPES
from app.services import quota_service
from app.services.audit_service import audit

MAX_KEYS = 10
DEFAULT_SCOPES = ["chat:write", "conversations:read"]


def key_hash(secret: str) -> bytes:
    return hmac_sha256(secret)


def key_out(k: ApiKey) -> dict[str, Any]:
    return {
        "id": str(k.id),
        "name": k.name,
        "key_prefix": k.key_prefix,
        "scopes": k.scopes,
        "created_at": k.created_at,
        "last_used_at": k.last_used_at,
        "expires_at": k.expires_at,
    }


async def create(
    db: AsyncSession,
    user_id: uuid.UUID,
    plan_key: str,
    name: str,
    scopes: list[str] | None,
    expires_in_days: int | None,
    request_id: str,
) -> dict[str, Any]:
    if not (await quota_service.plan_limits(db, plan_key)).get("api_access"):
        raise AppError(
            ErrorCode.PLAN_FEATURE_UNAVAILABLE, "API access is available on the Plus and Pro plans."
        )
    count = await db.scalar(
        select(func.count()).where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
    )
    if (count or 0) >= MAX_KEYS:
        raise AppError(ErrorCode.LIMIT_REACHED, "You can have up to 10 active API keys.")
    scopes = sorted(set(scopes or DEFAULT_SCOPES))
    if not set(scopes) <= set(API_SCOPES):
        raise AppError(
            ErrorCode.VALIDATION_ERROR, details=[{"field": "scopes", "issue": "invalid"}]
        )
    secret = new_api_key()
    k = ApiKey(
        user_id=user_id,
        name=name,
        key_prefix=secret[:16],
        key_hash=key_hash(secret),
        scopes=scopes,
        expires_at=datetime.now(UTC) + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    db.add(k)
    await db.flush()
    audit(
        db,
        "api_key.created",
        actor_user_id=user_id,
        target_type="api_key",
        target_id=k.id,
        request_id=request_id,
        metadata={"key_prefix": k.key_prefix, "scopes": scopes},
    )
    await db.commit()
    return {**key_out(k), "secret": secret}


async def list_keys(db: AsyncSession, user_id: uuid.UUID) -> list[ApiKey]:
    return list(
        (
            await db.execute(
                select(ApiKey)
                .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
                .order_by(ApiKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def rename(db: AsyncSession, user_id: uuid.UUID, key_id: uuid.UUID, name: str) -> ApiKey:
    k = await db.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None)
        )
    )
    if k is None:
        raise not_found()
    k.name = name
    await db.commit()
    return k


async def revoke(
    db: AsyncSession,
    user_id: uuid.UUID,
    key_id: uuid.UUID,
    request_id: str,
    actor_type: str = "user",
) -> None:
    k = await db.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None)
        )
    )
    if k is None:
        raise not_found()
    k.revoked_at = datetime.now(UTC)
    audit(
        db,
        "api_key.revoked",
        actor_user_id=user_id,
        actor_type=actor_type,
        target_type="api_key",
        target_id=k.id,
        request_id=request_id,
    )
    await db.commit()
    try:
        await get_redis().delete(rkey("apikey", k.key_hash.hex()))
    except Exception:
        pass


async def revoke_all(db: AsyncSession, user_id: uuid.UUID) -> None:
    for k in await list_keys(db, user_id):
        k.revoked_at = datetime.now(UTC)
        try:
            await get_redis().delete(rkey("apikey", k.key_hash.hex()))
        except Exception:
            pass


async def resolve(db: AsyncSession, secret: str, ip: str | None) -> dict[str, Any] | None:
    """Returns principal fields for a valid key, cached 60s (docs/09 §12)."""
    h = key_hash(secret)
    key = rkey("apikey", h.hex())
    try:
        if cached := await get_redis().get(key):
            return dict(json.loads(cached))
    except Exception:
        pass
    row = (
        await db.execute(
            select(ApiKey, User)
            .join(User, User.id == ApiKey.user_id)
            .where(
                ApiKey.key_hash == h,
                ApiKey.revoked_at.is_(None),
                (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > datetime.now(UTC)),
                User.deleted_at.is_(None),
                User.status == "active",
            )
        )
    ).first()
    if row is None:
        return None
    k, user = row
    info = {
        "api_key_id": str(k.id),
        "user_id": str(user.id),
        "role": user.role,
        "plan_key": user.plan_key,
        "created_at": user.created_at.isoformat(),
        "scopes": list(k.scopes),
    }
    now = datetime.now(UTC)
    if k.last_used_at is None or k.last_used_at < now - timedelta(minutes=1):
        k.last_used_at, k.last_used_ip = now, ip
        await db.commit()
    try:
        await get_redis().set(key, json.dumps(info), ex=60)
    except Exception:
        pass
    return info
