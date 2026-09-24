"""Typed system settings registry backed by system_settings + Redis cache (docs/36 §11)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.redis import get_redis, rkey
from app.models import SystemSetting


class SettingDef(BaseModel):
    type_: Any
    default: Any
    description: str
    public: bool = False


REGISTRY: dict[str, SettingDef] = {
    "signups_enabled": SettingDef(
        type_=bool, default=True, description="Allow new signups", public=True
    ),
    "block_disposable_emails": SettingDef(
        type_=bool, default=True, description="Reject disposable email domains"
    ),
    "chat_enabled": SettingDef(
        type_=bool, default=True, description="Emergency chat kill switch", public=True
    ),
    "maintenance_banner": SettingDef(
        type_=str | None, default=None, description="Banner shown in the app", public=True
    ),
    "disabled_model_keys": SettingDef(type_=list[str], default=[], description="Disabled models"),
    "disabled_tools": SettingDef(type_=list[str], default=[], description="Disabled tools"),
    "global_daily_token_budget": SettingDef(
        type_=int | None, default=None, description="Global Groq token budget per UTC day"
    ),
    "memory_extraction_enabled": SettingDef(
        type_=bool, default=True, description="Global memory extraction switch"
    ),
}
CACHE_TTL = 30


async def get_all(db: AsyncSession) -> dict[str, Any]:
    redis = get_redis()
    key = rkey("settings")
    try:
        cached = await redis.get(key)
        if cached:
            return dict(json.loads(cached))
    except Exception:
        pass
    values = {k: d.default for k, d in REGISTRY.items()}
    for row in (await db.execute(select(SystemSetting))).scalars():
        if row.key in REGISTRY:
            values[row.key] = row.value
    try:
        await redis.set(key, json.dumps(values), ex=CACHE_TTL)
    except Exception:
        pass
    return values


async def get(db: AsyncSession, key: str) -> Any:
    return (await get_all(db))[key]


async def set_value(db: AsyncSession, key: str, value: Any, actor: uuid.UUID) -> Any:
    if key not in REGISTRY:
        raise AppError(ErrorCode.RESOURCE_NOT_FOUND)
    try:
        value = TypeAdapter(REGISTRY[key].type_).validate_python(value)
    except Exception as e:
        raise AppError(
            ErrorCode.VALIDATION_ERROR, details=[{"field": "value", "issue": "invalid_type"}]
        ) from e
    stmt = insert(SystemSetting).values(key=key, value=value, updated_by=actor)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[SystemSetting.key], set_={"value": value, "updated_by": actor}
        )
    )
    try:
        await get_redis().delete(rkey("settings"))
    except Exception:
        pass
    return value
