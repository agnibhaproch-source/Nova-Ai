"""Async engine, session factory and request-scoped session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    s = get_settings()
    connect_args: dict[str, object] = {
        "server_settings": {"statement_timeout": "15000", "application_name": "nova-api"}
    }
    if s.DATABASE_USE_PGBOUNCER:
        connect_args |= {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    return create_async_engine(
        s.DATABASE_URL,
        pool_size=s.DATABASE_POOL_SIZE,
        max_overflow=s.DATABASE_MAX_OVERFLOW,
        pool_timeout=s.DATABASE_POOL_TIMEOUT,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=connect_args,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
