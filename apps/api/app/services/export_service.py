"""Data export ZIP (docs/10 §9)."""

from __future__ import annotations

import json
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, not_found
from app.db.session import get_sessionmaker
from app.files import storage
from app.models import (
    Conversation,
    DataExport,
    File,
    Memory,
    Message,
    MessagePart,
    Payment,
    UsageDaily,
    User,
    UserPreferences,
)
from app.services.audit_service import audit
from app.workers.queue import enqueue

MAX_FILES_BYTES = int(1.5 * 1024**3)


def export_out(e: DataExport) -> dict[str, Any]:
    return {
        "id": str(e.id),
        "status": e.status,
        "size_bytes": e.size_bytes,
        "created_at": e.created_at,
        "completed_at": e.completed_at,
        "expires_at": e.expires_at,
        "error_message": e.error_message,
    }


async def request_export(
    db: AsyncSession, user_id: uuid.UUID, include_files: bool, request_id: str
) -> DataExport:
    recent = await db.scalar(
        select(DataExport).where(
            DataExport.user_id == user_id,
            DataExport.created_at > datetime.now(UTC) - timedelta(hours=24),
        )
    )
    if recent is not None:
        raise AppError(ErrorCode.EXPORT_RATE_LIMITED)
    e = DataExport(user_id=user_id)
    db.add(e)
    await db.flush()
    audit(
        db,
        "user.export.requested",
        actor_user_id=user_id,
        target_type="export",
        target_id=e.id,
        request_id=request_id,
    )
    await db.commit()
    await enqueue("build_export", str(e.id), include_files)
    return e


async def download(
    db: AsyncSession, user_id: uuid.UUID, export_id: uuid.UUID, request_id: str
) -> str:
    e = await db.scalar(
        select(DataExport).where(DataExport.id == export_id, DataExport.user_id == user_id)
    )
    if e is None:
        raise not_found()
    if e.status in ("queued", "running"):
        raise AppError(ErrorCode.EXPORT_NOT_READY)
    if (
        e.status != "ready"
        or not e.storage_key
        or (e.expires_at and e.expires_at < datetime.now(UTC))
    ):
        raise AppError(ErrorCode.EXPORT_EXPIRED)
    audit(
        db,
        "user.export.downloaded",
        actor_user_id=user_id,
        target_type="export",
        target_id=e.id,
        request_id=request_id,
    )
    await db.commit()
    return await storage.presigned_get(e.storage_key, filename="nova-export.zip")


def _j(obj: Any) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False, indent=2)


async def build(export_id: uuid.UUID, include_files: bool) -> None:
    sm = get_sessionmaker()
    async with sm() as db:
        e = await db.get(DataExport, export_id)
        if e is None:
            return
        e.status = "running"
        await db.commit()
        uid = e.user_id
    try:
        with tempfile.TemporaryDirectory(prefix="nova-export-") as tmp:
            path = Path(tmp) / "export.zip"
            async with sm() as db:
                user = await db.get(User, uid)
                prefs = await db.get(UserPreferences, uid)
                assert user is not None
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                    z.writestr(
                        "profile.json",
                        _j(
                            {
                                "id": user.id,
                                "email": user.email,
                                "display_name": user.display_name,
                                "plan_key": user.plan_key,
                                "created_at": user.created_at,
                                "preferences": {
                                    c.name: getattr(prefs, c.key, None)
                                    for c in UserPreferences.__table__.columns
                                }
                                if prefs
                                else None,
                            }
                        ),
                    )
                    convs = (
                        (await db.execute(select(Conversation).where(Conversation.user_id == uid)))
                        .scalars()
                        .all()
                    )
                    for c in convs:
                        msgs = (
                            (
                                await db.execute(
                                    select(Message)
                                    .where(Message.conversation_id == c.id)
                                    .order_by(Message.created_at)
                                )
                            )
                            .scalars()
                            .all()
                        )
                        parts = (
                            (
                                await db.execute(
                                    select(MessagePart).where(
                                        MessagePart.message_id.in_([m.id for m in msgs])
                                    )
                                )
                            )
                            .scalars()
                            .all()
                            if msgs
                            else []
                        )
                        by: dict[uuid.UUID, list[dict[str, Any]]] = {}
                        for p in parts:
                            by.setdefault(p.message_id, []).append(
                                {
                                    "position": p.position,
                                    "type": p.type,
                                    "text": p.text_content,
                                    "data": p.data,
                                }
                            )
                        z.writestr(
                            f"conversations/{c.id}.json",
                            _j(
                                {
                                    "id": c.id,
                                    "title": c.title,
                                    "created_at": c.created_at,
                                    "deleted_at": c.deleted_at,
                                    "messages": [
                                        {
                                            "id": m.id,
                                            "parent_message_id": m.parent_message_id,
                                            "role": m.role,
                                            "status": m.status,
                                            "created_at": m.created_at,
                                            "model_key": m.model_key,
                                            "parts": by.get(m.id, []),
                                        }
                                        for m in msgs
                                    ],
                                }
                            ),
                        )
                    mems = (
                        (
                            await db.execute(
                                select(Memory).where(
                                    Memory.user_id == uid, Memory.deleted_at.is_(None)
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                    z.writestr(
                        "memories.json",
                        _j(
                            [
                                {
                                    "content": m.content,
                                    "category": m.category,
                                    "created_at": m.created_at,
                                }
                                for m in mems
                            ]
                        ),
                    )
                    files = (
                        (
                            await db.execute(
                                select(File).where(File.user_id == uid, File.deleted_at.is_(None))
                            )
                        )
                        .scalars()
                        .all()
                    )
                    z.writestr(
                        "files.json",
                        _j(
                            [
                                {
                                    "id": f.id,
                                    "filename": f.original_filename,
                                    "size_bytes": f.size_bytes,
                                    "status": f.status,
                                    "created_at": f.created_at,
                                }
                                for f in files
                            ]
                        ),
                    )
                    usage = (
                        (await db.execute(select(UsageDaily).where(UsageDaily.user_id == uid)))
                        .scalars()
                        .all()
                    )
                    z.writestr(
                        "usage.json",
                        _j(
                            [
                                {
                                    "day": u.day,
                                    "kind": u.kind,
                                    "requests": u.request_count,
                                    "prompt_tokens": u.prompt_tokens,
                                    "completion_tokens": u.completion_tokens,
                                }
                                for u in usage
                            ]
                        ),
                    )
                    pays = (
                        (await db.execute(select(Payment).where(Payment.user_id == uid)))
                        .scalars()
                        .all()
                    )
                    z.writestr(
                        "payments.json",
                        _j(
                            [
                                {
                                    "amount_paise": p.amount_paise,
                                    "status": p.status,
                                    "created_at": p.created_at,
                                }
                                for p in pays
                            ]
                        ),
                    )
                    note = (
                        "NOVA AI data export. JSON files contain your data; files/ holds "
                        "your uploads.\n"
                    )
                    total = 0
                    if include_files:
                        for f in files:
                            if f.status != "ready" or total + f.size_bytes > MAX_FILES_BYTES:
                                note += f"Skipped file {f.id} ({f.original_filename}).\n"
                                continue
                            data = await storage.get_bytes(f.storage_key)
                            total += len(data)
                            z.writestr(f"files/{f.id}-{f.original_filename}", data)
                    z.writestr("README.txt", note)
            key = f"users/{uid}/exports/{export_id}.zip"
            await storage.put(key, path.read_bytes(), "application/zip")
            async with sm() as db:
                e = await db.get(DataExport, export_id)
                assert e is not None
                e.status, e.storage_key, e.size_bytes = "ready", key, path.stat().st_size
                e.completed_at = datetime.now(UTC)
                e.expires_at = datetime.now(UTC) + timedelta(hours=24)
                await db.commit()
    except Exception:
        async with sm() as db:
            e = await db.get(DataExport, export_id)
            if e is not None:
                e.status, e.error_message = "failed", "The export failed. Please try again."
                await db.commit()
        raise
