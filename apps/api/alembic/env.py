"""Async Alembic environment. Uses DATABASE_MIGRATOR_URL when set (owner role)."""

import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine

import app.models
from alembic import context
from app.core.config import get_settings
from app.db.base import Base

target_metadata = Base.metadata
_only = {t for t in os.environ.get("NOVA_AUTOGEN_TABLES", "").split(",") if t}


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    if _only and type_ == "table":
        return name in _only
    if _only and hasattr(obj, "table"):
        return obj.table.name in _only
    return True


def _url() -> str:
    return os.environ.get("DATABASE_MIGRATOR_URL") or get_settings().DATABASE_URL


def do_run(connection):  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as conn:
        await conn.run_sync(do_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
