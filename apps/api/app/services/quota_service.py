"""Plan quotas with Redis counters and DB rebuild (docs/35 §6)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.redis import get_redis, rkey
from app.models import Message, Plan, UsageRecord

log = structlog.get_logger()


def _day(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%d")


def _month(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m")


def resets() -> dict[str, str]:
    now = datetime.now(UTC)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), UTC)
    nm = date(now.year + (now.month == 12), now.month % 12 + 1, 1)
    return {
        "daily_at": tomorrow.isoformat(),
        "monthly_at": datetime.combine(nm, datetime.min.time(), UTC).isoformat(),
    }


async def plan_limits(db: AsyncSession, plan_key: str) -> dict[str, Any]:
    plan = await db.get(Plan, plan_key)
    return dict(plan.limits) if plan else {}


async def _messages_today(db: AsyncSession, user_id: uuid.UUID) -> int:
    key = rkey("q", "msg", user_id, _day())
    try:
        v = await get_redis().get(key)
        if v is not None:
            return int(v)
    except RedisError:
        pass
    start = datetime.combine(datetime.now(UTC).date(), datetime.min.time(), UTC)
    n = int(
        await db.scalar(
            select(func.count()).where(
                Message.user_id == user_id, Message.role == "user", Message.created_at >= start
            )
        )
        or 0
    )
    try:
        await get_redis().set(key, n, ex=48 * 3600, nx=True)
    except RedisError:
        pass
    return n


async def tokens_this_month(db: AsyncSession, user_id: uuid.UUID) -> int:
    key = rkey("q", "tok", user_id, _month())
    try:
        v = await get_redis().get(key)
        if v is not None:
            return int(v)
    except RedisError:
        pass
    now = datetime.now(UTC)
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    n = int(
        await db.scalar(
            select(func.coalesce(func.sum(UsageRecord.total_tokens), 0)).where(
                UsageRecord.user_id == user_id,
                UsageRecord.created_at >= start,
                UsageRecord.kind != "eval",
            )
        )
        or 0
    )
    try:
        await get_redis().set(key, n, ex=40 * 86400, nx=True)
    except RedisError:
        pass
    return n


async def check_and_reserve_message(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    plan_key: str,
    estimated_tokens: int,
) -> None:
    limits = await plan_limits(db, plan_key)
    used = await _messages_today(db, user_id)
    limit = int(limits.get("messages_per_day", 0))
    if used >= limit:
        raise AppError(
            ErrorCode.QUOTA_EXCEEDED,
            f"You've reached your daily message limit ({limit}). Upgrade or wait until tomorrow.",
            details=[
                {
                    "quota": "messages_per_day",
                    "limit": limit,
                    "used": used,
                    "resets_at": resets()["daily_at"],
                }
            ],
            retry_after=_seconds_until(resets()["daily_at"]),
        )
    tok_limit = int(limits.get("monthly_token_quota", 0))
    tokens = await tokens_this_month(db, user_id)
    if tokens + estimated_tokens > tok_limit:
        raise AppError(
            ErrorCode.QUOTA_EXCEEDED,
            "You've used this month's token allowance. Upgrade for more.",
            details=[
                {
                    "quota": "monthly_token_quota",
                    "limit": tok_limit,
                    "used": tokens,
                    "resets_at": resets()["monthly_at"],
                }
            ],
        )
    try:
        key = rkey("q", "msg", user_id, _day())
        await get_redis().incr(key)
        await get_redis().expire(key, 48 * 3600)
    except RedisError:
        log.warning("quota.redis_unavailable")


def _seconds_until(iso: str) -> int:
    return max(1, int((datetime.fromisoformat(iso) - datetime.now(UTC)).total_seconds()))


async def release_message(user_id: uuid.UUID) -> None:
    try:
        await get_redis().decr(rkey("q", "msg", user_id, _day()))
    except RedisError:
        pass


async def add_tokens(user_id: uuid.UUID, tokens: int) -> None:
    if tokens <= 0:
        return
    try:
        key = rkey("q", "tok", user_id, _month())
        if await get_redis().exists(key):
            await get_redis().incrby(key, tokens)
    except RedisError:
        pass


async def quota_snapshot(db: AsyncSession, user_id: uuid.UUID, plan_key: str) -> dict[str, Any]:
    limits = await plan_limits(db, plan_key)
    msgs = await _messages_today(db, user_id)
    toks = await tokens_this_month(db, user_id)
    return {
        "plan_key": plan_key,
        "period_resets": resets(),
        "limits": limits,
        "used": {"messages_today": msgs, "tokens_month": toks},
        "messages_remaining_today": max(0, int(limits.get("messages_per_day", 0)) - msgs),
        "tokens_remaining_month": max(0, int(limits.get("monthly_token_quota", 0)) - toks),
    }
