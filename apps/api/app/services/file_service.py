"""FileService: presigned uploads, lifecycle, attachments, downloads, deletion (docs/18)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.core.errors import AppError, ErrorCode, not_found
from app.core.redis import get_redis, rkey
from app.files import storage
from app.files.validation import classify
from app.models import Conversation, ConversationFile, DocumentChunk, File
from app.services import analytics_service, quota_service
from app.workers.queue import enqueue

TERMINAL = {"ready", "failed", "rejected", "deleted"}
MAX_FILES_PER_CONVERSATION = 50


def file_out(f: File) -> dict[str, Any]:
    meta = f.metadata_ or {}
    return {
        "id": str(f.id),
        "filename": f.original_filename,
        "extension": f.extension,
        "mime_type": f.declared_mime_type,
        "size_bytes": f.size_bytes,
        "kind": f.kind,
        "purpose": f.purpose,
        "status": f.status,
        "stage": meta.get("stage"),
        "progress": meta.get("progress"),
        "indexed": f.chunk_count > 0,
        "error_code": f.error_code,
        "error_message": f.error_message,
        "page_count": f.page_count,
        "chunk_count": f.chunk_count,
        "created_at": f.created_at,
        "processed_at": f.processed_at,
    }


async def get_owned(db: AsyncSession, user_id: uuid.UUID, file_id: uuid.UUID) -> File:
    f = await db.scalar(
        select(File).where(File.id == file_id, File.user_id == user_id, File.deleted_at.is_(None))
    )
    if f is None:
        raise not_found()
    return f


async def _storage_used(db: AsyncSession, user_id: uuid.UUID) -> int:
    key = rkey("storage", user_id)
    try:
        v = await get_redis().get(key)
        if v is not None:
            return int(v)
    except Exception:
        pass
    used = int(
        await db.scalar(
            select(func.coalesce(func.sum(File.size_bytes), 0)).where(
                File.user_id == user_id, File.deleted_at.is_(None)
            )
        )
        or 0
    )
    try:
        await get_redis().set(key, used, ex=300)
    except Exception:
        pass
    return used


async def _bump_storage(user_id: uuid.UUID, delta: int) -> None:
    try:
        if await get_redis().exists(rkey("storage", user_id)):
            await get_redis().incrby(rkey("storage", user_id), delta)
    except Exception:
        pass


async def initiate(
    db: AsyncSession,
    p: Principal,
    *,
    filename: str,
    size_bytes: int,
    mime_type: str,
    purpose: str,
    conversation_id: uuid.UUID | None,
) -> dict[str, Any]:
    clean, ext, rule = classify(filename, mime_type)
    limits = await quota_service.plan_limits(db, p.plan_key)
    max_mb = (
        2
        if purpose == "avatar"
        else int(limits.get("max_image_mb" if rule.kind == "image" else "max_document_mb", 10))
    )
    if size_bytes > max_mb * 1024 * 1024:
        raise AppError(
            ErrorCode.FILE_TOO_LARGE, f"This file is larger than your plan allows ({max_mb} MB)."
        )
    if await _storage_used(db, p.uid) + size_bytes > int(limits.get("storage_mb", 100)) * 1024**2:
        raise AppError(ErrorCode.STORAGE_QUOTA_EXCEEDED)
    day = datetime.now(UTC).strftime("%Y%m%d")
    try:
        n = int(await get_redis().incr(rkey("q", "up", p.uid, day)))
        await get_redis().expire(rkey("q", "up", p.uid, day), 48 * 3600)
    except Exception:
        n = 0
    if n > int(limits.get("uploads_per_day", 10)):
        raise AppError(ErrorCode.QUOTA_EXCEEDED, "You've reached today's upload limit.")
    if conversation_id is not None:
        conv = await db.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id, Conversation.user_id == p.uid
            )
        )
        if conv is None:
            raise not_found()
    fid = uuid.uuid4()
    f = File(
        id=fid,
        user_id=p.uid,
        original_filename=clean,
        extension=ext,
        declared_mime_type=mime_type,
        size_bytes=size_bytes,
        storage_key=f"users/{p.uid}/files/{fid}",
        kind=rule.kind,
        purpose=purpose,
        metadata_={"conversation_id": str(conversation_id) if conversation_id else None},
    )
    db.add(f)
    await db.commit()
    await db.refresh(f)
    upload = await storage.presigned_post(f.storage_key, mime_type, size_bytes)
    return {
        "file": file_out(f),
        "upload": {**upload, "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat()},
    }


async def complete(db: AsyncSession, p: Principal, file_id: uuid.UUID) -> File:
    f = await get_owned(db, p.uid, file_id)
    if f.status != "pending_upload":
        return f
    obj = await storage.head(f.storage_key)
    if (
        obj is None
        or int(obj.get("ContentLength", 0)) <= 0
        or int(obj["ContentLength"]) > f.size_bytes
    ):
        f.status, f.error_code = "rejected", "UPLOAD_INVALID"
        await db.commit()
        await storage.delete_prefix(f.storage_key)
        raise AppError(ErrorCode.UPLOAD_INVALID)
    f.size_bytes = int(obj["ContentLength"])
    f.status = "uploaded"
    f.metadata_ = {**(f.metadata_ or {}), "stage": "queued", "progress": 0}
    cid = (f.metadata_ or {}).get("conversation_id")
    if cid:
        await db.execute(
            insert(ConversationFile)
            .values(conversation_id=uuid.UUID(cid), file_id=f.id)
            .on_conflict_do_nothing()
        )
    await analytics_service.track(
        db,
        "file_uploaded",
        user_id=p.uid,
        properties={"kind": f.kind, "extension": f.extension, "purpose": f.purpose},
    )
    await db.commit()
    await db.refresh(f)
    await _bump_storage(p.uid, f.size_bytes)
    await enqueue("process_file", str(f.id), _job_id=f"process_file:{f.id}:{f.updated_at}")
    return f


async def list_files(
    db: AsyncSession, user_id: uuid.UUID, *, kind: str | None, q: str | None, limit: int
) -> list[File]:
    stmt = select(File).where(
        File.user_id == user_id, File.deleted_at.is_(None), File.purpose == "attachment"
    )
    if kind:
        stmt = stmt.where(File.kind == kind)
    if q:
        stmt = stmt.where(File.original_filename.ilike(f"%{q}%"))
    return list(
        (await db.execute(stmt.order_by(File.created_at.desc()).limit(limit))).scalars().all()
    )


async def download_url(
    db: AsyncSession, user_id: uuid.UUID, file_id: uuid.UUID, inline: bool = False
) -> str:
    f = await get_owned(db, user_id, file_id)
    if f.status not in ("ready", "failed"):
        raise AppError(ErrorCode.FILE_NOT_READY)
    if inline and f.kind != "image":
        raise AppError(ErrorCode.INVALID_FILE)
    return await storage.presigned_get(
        f.storage_key, filename=f.original_filename, inline=inline, expires=3600 if inline else 300
    )


async def retry(db: AsyncSession, user_id: uuid.UUID, file_id: uuid.UUID) -> File:
    f = await get_owned(db, user_id, file_id)
    if f.status != "failed":
        raise AppError(ErrorCode.INVALID_FILE_STATE)
    f.status, f.error_code, f.error_message = "uploaded", None, None
    await db.commit()
    await db.refresh(f)
    await enqueue("process_file", str(f.id), _job_id=f"process_file:{f.id}:retry:{f.updated_at}")
    return f


async def soft_delete(db: AsyncSession, user_id: uuid.UUID, file_id: uuid.UUID) -> None:
    f = await get_owned(db, user_id, file_id)
    f.status, f.deleted_at = "deleted", datetime.now(UTC)
    await db.execute(delete(DocumentChunk).where(DocumentChunk.file_id == f.id))
    await db.execute(delete(ConversationFile).where(ConversationFile.file_id == f.id))
    await db.commit()
    await _bump_storage(user_id, -f.size_bytes)
    await enqueue("purge_file", str(f.id))


async def attach(
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    file_id: uuid.UUID,
    message_id: uuid.UUID | None = None,
) -> File:
    conv = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
    )
    if conv is None:
        raise not_found()
    f = await get_owned(db, user_id, file_id)
    count = await db.scalar(
        select(func.count()).where(ConversationFile.conversation_id == conversation_id)
    )
    if (count or 0) >= MAX_FILES_PER_CONVERSATION:
        raise AppError(ErrorCode.LIMIT_REACHED)
    await db.execute(
        insert(ConversationFile)
        .values(conversation_id=conversation_id, file_id=f.id, attached_by_message_id=message_id)
        .on_conflict_do_nothing()
    )
    return f


async def detach(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID, file_id: uuid.UUID
) -> None:
    conv = await db.scalar(
        select(Conversation.id).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if conv is None:
        raise not_found()
    await db.execute(
        delete(ConversationFile).where(
            ConversationFile.conversation_id == conversation_id, ConversationFile.file_id == file_id
        )
    )
    await db.commit()


async def conversation_files(
    db: AsyncSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[File]:
    conv = await db.scalar(
        select(Conversation.id).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )
    if conv is None:
        raise not_found()
    return list(
        (
            await db.execute(
                select(File)
                .join(ConversationFile, ConversationFile.file_id == File.id)
                .where(
                    ConversationFile.conversation_id == conversation_id, File.deleted_at.is_(None)
                )
                .order_by(ConversationFile.created_at)
            )
        )
        .scalars()
        .all()
    )
