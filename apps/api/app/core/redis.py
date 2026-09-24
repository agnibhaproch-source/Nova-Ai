"""Process-wide Redis client (asyncio)."""

from __future__ import annotations

from functools import lru_cache

from redis.asyncio import BlockingConnectionPool, Redis

from app.core.config import get_settings


@lru_cache
def get_redis() -> Redis:
    pool = BlockingConnectionPool.from_url(
        get_settings().REDIS_URL, max_connections=500, timeout=5, decode_responses=True
    )
    return Redis(connection_pool=pool)


def rkey(*parts: object) -> str:
    """Namespaced key: nova:{env}:part1:part2."""
    return get_settings().redis_prefix + ":".join(str(p) for p in parts)
