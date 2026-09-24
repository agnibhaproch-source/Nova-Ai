"""ARQ worker: jobs and cron schedule (docs/05 §6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from arq import cron
from sqlalchemy import delete, select, text, update

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import get_redis, rkey
from app.db.session import get_sessionmaker
from app.models import Conversation, Session, User
from app.services import conversation_service, email_service, title_service
from app.streaming import runner
from app.workers.queue import redis_settings

log = structlog.get_logger("app.worker")


async def send_email(ctx: dict[str, Any], to: str, template: str, params: dict[str, str]) -> None:
    await email_service.send_template(to, template, **params)
    log.info("job.completed", job_name="send_email", template=template)


async def purge_user(ctx: dict[str, Any], user_id: str) -> None:
    uid = uuid.UUID(user_id)
    async with get_sessionmaker()() as db:
        user = await db.get(User, uid)
        if user is None or user.status != "deleted":
            return
        conv_ids = list(
            (await db.execute(select(Conversation.id).where(Conversation.user_id == uid))).scalars()
        )
        await conversation_service._hard_delete_ids(db, conv_ids)
        await db.execute(delete(User).where(User.id == uid))
        await db.commit()
    from app.files import storage

    await storage.delete_prefix(f"users/{uid}/")
    log.info("job.completed", job_name="purge_user")


async def _conversation_key(conversation_id: uuid.UUID) -> tuple[bool, str | None]:
    """(ok, key): BYOK jobs use the conversation's key; no key → skip the job."""
    from app.ai.groq import keys as groq_keys
    from app.core.errors import AppError

    try:
        return True, await groq_keys.for_conversation(conversation_id)
    except AppError:
        log.info("job.skipped_no_groq_key")
        return False, None


async def generate_title(ctx: dict[str, Any], conversation_id: str) -> None:
    from app.ai.groq import keys as groq_keys

    ok, key = await _conversation_key(uuid.UUID(conversation_id))
    if ok:
        with groq_keys.using(key):
            await title_service.generate_title(uuid.UUID(conversation_id))


async def maybe_summarize(ctx: dict[str, Any], conversation_id: str) -> None:
    lock = rkey("summary_lock", conversation_id)
    if not await get_redis().set(lock, "1", nx=True, ex=120):
        return
    try:
        from app.ai.groq import keys as groq_keys

        ok, key = await _conversation_key(uuid.UUID(conversation_id))
        if ok:
            with groq_keys.using(key):
                await title_service.maybe_summarize(uuid.UUID(conversation_id))
    finally:
        await get_redis().delete(lock)


async def reap_stale_generations(ctx: dict[str, Any]) -> None:
    n = await runner.reap_stale()
    if n:
        log.warning("reaper.interrupted", count=n)


async def purge_trashed_conversations(ctx: dict[str, Any]) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=conversation_service.TRASH_DAYS)
    async with get_sessionmaker()() as db:
        ids = list(
            (
                await db.execute(
                    select(Conversation.id).where(Conversation.deleted_at < cutoff).limit(1000)
                )
            ).scalars()
        )
        await conversation_service._hard_delete_ids(db, ids)
        await db.commit()


async def purge_empty_conversations(ctx: dict[str, Any]) -> None:
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    async with get_sessionmaker()() as db:
        await db.execute(
            delete(Conversation).where(
                Conversation.message_count == 0, Conversation.created_at < cutoff
            )
        )
        await db.commit()


async def purge_expired_sessions(ctx: dict[str, Any]) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=90)
    async with get_sessionmaker()() as db:
        await db.execute(
            delete(Session).where((Session.expires_at < cutoff) | (Session.revoked_at < cutoff))
        )
        await db.execute(
            update(Session)
            .where(
                Session.created_at < datetime.now(UTC) - timedelta(days=180),
                Session.ip_address.is_not(None),
            )
            .values(ip_address=None)
        )
        await db.commit()


async def aggregate_usage_daily(ctx: dict[str, Any]) -> None:
    """Recomputes today's and yesterday's usage_daily rows from usage_records (idempotent)."""
    async with get_sessionmaker()() as db:
        await db.execute(
            text(
                """
            INSERT INTO usage_daily (user_id, day, kind, model_key, request_count, error_count,
                                     prompt_tokens, completion_tokens, estimated_cost_usd_micros)
            SELECT user_id, created_at::date, kind, COALESCE(model_key, ''), count(*),
                   count(*) FILTER (WHERE status = 'error'), sum(prompt_tokens),
                   sum(completion_tokens), COALESCE(sum(estimated_cost_usd_micros), 0)
              FROM usage_records
             WHERE user_id IS NOT NULL AND created_at >= current_date - 1
             GROUP BY 1, 2, 3, 4
            ON CONFLICT (user_id, day, kind, model_key) DO UPDATE SET
              request_count = EXCLUDED.request_count, error_count = EXCLUDED.error_count,
              prompt_tokens = EXCLUDED.prompt_tokens,
              completion_tokens = EXCLUDED.completion_tokens,
              estimated_cost_usd_micros = EXCLUDED.estimated_cost_usd_micros
            """
            )
        )
        await db.commit()


async def process_file(ctx: dict[str, Any], file_id: str) -> None:
    from app.documents.pipeline import process_file as run

    await run(uuid.UUID(file_id))


async def purge_file(ctx: dict[str, Any], file_id: str) -> None:
    from app.files import storage
    from app.models import File

    async with get_sessionmaker()() as db:
        f = await db.get(File, uuid.UUID(file_id))
        if f is None or f.deleted_at is None:
            return
        await storage.delete_prefix(f.storage_key)
        await db.delete(f)
        await db.commit()


async def extract_memories(ctx: dict[str, Any], message_id: str) -> None:
    from app.ai.groq import keys as groq_keys
    from app.models import Message
    from app.services import memory_service

    async with get_sessionmaker()() as db:
        msg = await db.get(Message, uuid.UUID(message_id))
    if msg is None:
        return
    ok, key = await _conversation_key(msg.conversation_id)
    if ok:
        with groq_keys.using(key):
            await memory_service.extract_from_message(uuid.UUID(message_id))


async def decay_memories(ctx: dict[str, Any]) -> None:
    from app.services import memory_service

    await memory_service.decay()


async def build_export(ctx: dict[str, Any], export_id: str, include_files: bool = True) -> None:
    from app.services import export_service

    await export_service.build(uuid.UUID(export_id), include_files)


async def requeue_stuck_files(ctx: dict[str, Any]) -> None:
    """Recovers file jobs lost with Redis and cleans orphan uploads (docs/48 F8)."""
    from app.models import File
    from app.workers.queue import enqueue

    cutoff = datetime.now(UTC) - timedelta(minutes=15)
    async with get_sessionmaker()() as db:
        ids = list(
            (
                await db.execute(
                    select(File.id)
                    .where(
                        File.status.in_(("uploaded", "scanning", "processing")),
                        File.updated_at < cutoff,
                    )
                    .limit(100)
                )
            ).scalars()
        )
        orphans = list(
            (
                await db.execute(
                    select(File)
                    .where(
                        File.status == "pending_upload",
                        File.created_at < datetime.now(UTC) - timedelta(hours=1),
                    )
                    .limit(200)
                )
            ).scalars()
        )
        for f in orphans:
            f.status, f.deleted_at = "deleted", datetime.now(UTC)
        await db.commit()
    for fid in ids:
        await enqueue("process_file", str(fid), _job_id=f"process_file:{fid}:requeue")
    for f in orphans:
        await enqueue("purge_file", str(f.id))


async def purge_deleted_users(ctx: dict[str, Any]) -> None:
    async with get_sessionmaker()() as db:
        ids = list((await db.execute(select(User.id).where(User.status == "deleted"))).scalars())
    for uid in ids:
        await purge_user(ctx, str(uid))


async def expire_data_exports(ctx: dict[str, Any]) -> None:
    from app.files import storage
    from app.models import DataExport

    async with get_sessionmaker()() as db:
        rows = (
            await db.execute(
                select(DataExport).where(
                    DataExport.status == "ready", DataExport.expires_at < datetime.now(UTC)
                )
            )
        ).scalars()
        for e in rows:
            if e.storage_key:
                await storage.delete_prefix(e.storage_key)
            e.status = "expired"
        await db.commit()


async def billing_maintenance(ctx: dict[str, Any]) -> None:
    from app.services import billing_service

    async with get_sessionmaker()() as db:
        await billing_service.downgrade_halted(db)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging("nova-worker")
    from app.main import _init_models

    _init_models()


async def heartbeat(ctx: dict[str, Any]) -> None:
    await get_redis().set(rkey("worker", "heartbeat"), datetime.now(UTC).isoformat(), ex=60)


class WorkerSettings:
    functions = [
        send_email,
        purge_user,
        generate_title,
        maybe_summarize,
        process_file,
        purge_file,
        extract_memories,
        build_export,
    ]
    cron_jobs = [
        cron(reap_stale_generations, second={0, 30}, unique=True),
        cron(heartbeat, second={0, 15, 30, 45}, unique=True),
        cron(aggregate_usage_daily, minute=set(range(0, 60, 5)), second=10, unique=True),
        cron(purge_empty_conversations, minute=7, unique=True),
        cron(purge_trashed_conversations, hour=2, minute=0, unique=True),
        cron(purge_expired_sessions, hour=3, minute=0, unique=True),
        cron(requeue_stuck_files, minute=set(range(2, 60, 5)), unique=True),
        cron(purge_deleted_users, minute=15, unique=True),
        cron(expire_data_exports, minute=25, unique=True),
        cron(decay_memories, hour=4, minute=30, unique=True),
        cron(billing_maintenance, minute=45, unique=True),
    ]
    on_startup = startup
    redis_settings = redis_settings()
    max_jobs = 8
    job_timeout = 900
    max_tries = 5


__all__ = ["WorkerSettings", "get_settings"]
