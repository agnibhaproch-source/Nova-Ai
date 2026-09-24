"""Enqueue ARQ jobs from the API. Call only after the DB transaction has committed."""

from __future__ import annotations

from typing import Any

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

log = structlog.get_logger()
_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().REDIS_URL)


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def enqueue(function: str, *args: Any, _job_id: str | None = None, **kwargs: Any) -> None:
    try:
        pool = await get_pool()
        await pool.enqueue_job(function, *args, _job_id=_job_id, **kwargs)
    except Exception:
        # Jobs are recoverable via reconciliation crons; never fail the user request here.
        log.exception("job.enqueue_failed", job_name=function)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
