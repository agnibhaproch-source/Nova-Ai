"""Memories, tools, voice, API keys, exports, reports (docs/31 §3, §4, §9, §10, §13)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models_registry import get_registry
from app.api.deps import (
    Principal,
    rate_limit,
    request_id,
    require_csrf,
    require_scopes,
    require_user,
)
from app.core.errors import AppError, ErrorCode
from app.db.session import get_db
from app.models import Message, ModerationFlag
from app.schemas.common import Envelope, In, ListEnvelope
from app.services import (
    api_key_service,
    export_service,
    memory_service,
    message_service,
    quota_service,
    settings_service,
    user_service,
    voice_service,
)
from app.tools import engine as tool_engine

router = APIRouter()
Category = Literal["preference", "biographical", "project", "instruction", "other"]


async def session_only(p: Principal = Depends(require_csrf)) -> Principal:
    if p.auth_method != "session":
        raise AppError(ErrorCode.FORBIDDEN)
    return p


# ------------------------------------------------------------------ memories
class MemoryIn(In):
    content: str = Field(min_length=3, max_length=500)
    category: Category = "other"
    importance: int = Field(default=3, ge=1, le=5)


class MemoryPatchIn(In):
    content: str | None = Field(default=None, min_length=3, max_length=500)
    category: Category | None = None
    importance: int | None = Field(default=None, ge=1, le=5)


@router.get(
    "/memories",
    tags=["memories"],
    operation_id="memories_list",
    dependencies=[Depends(rate_limit("api_read"))],
)
async def list_memories(
    q: str | None = Query(default=None, max_length=100),
    category: Category | None = None,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("memories:read")),
) -> ListEnvelope[dict[str, Any]]:
    rows = await memory_service.list_memories(db, p.uid, q, category)
    return ListEnvelope(data=[memory_service.memory_out(m) for m in rows])


@router.post(
    "/memories",
    status_code=status.HTTP_201_CREATED,
    tags=["memories"],
    operation_id="memories_create",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def create_memory(
    body: MemoryIn, db: AsyncSession = Depends(get_db), p: Principal = Depends(session_only)
) -> Envelope[dict[str, Any]]:
    m = await memory_service.create(db, p.uid, body.content, body.category, body.importance)
    await db.commit()
    return Envelope(data=memory_service.memory_out(m))


@router.get("/memories/notifications", tags=["memories"], operation_id="memories_notifications")
async def notifications(p: Principal = Depends(require_user)) -> ListEnvelope[dict[str, Any]]:
    return ListEnvelope(data=await memory_service.pop_notifications(p.uid))


@router.patch(
    "/memories/{memory_id}",
    tags=["memories"],
    operation_id="memories_update",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryPatchIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(session_only),
) -> Envelope[dict[str, Any]]:
    m = await memory_service.update_memory(
        db, p.uid, memory_id, body.model_dump(exclude_unset=True)
    )
    return Envelope(data=memory_service.memory_out(m))


@router.delete(
    "/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["memories"],
    operation_id="memories_delete",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def delete_memory(
    memory_id: uuid.UUID, db: AsyncSession = Depends(get_db), p: Principal = Depends(session_only)
) -> Response:
    await memory_service.delete_memory(db, p.uid, memory_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/memories/{memory_id}/restore",
    tags=["memories"],
    operation_id="memories_restore",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def restore_memory(
    memory_id: uuid.UUID, db: AsyncSession = Depends(get_db), p: Principal = Depends(session_only)
) -> Envelope[dict[str, Any]]:
    return Envelope(
        data=memory_service.memory_out(await memory_service.restore(db, p.uid, memory_id))
    )


@router.delete(
    "/memories",
    tags=["memories"],
    operation_id="memories_delete_all",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def delete_all(
    confirm: bool = False, db: AsyncSession = Depends(get_db), p: Principal = Depends(session_only)
) -> Envelope[dict[str, int]]:
    if not confirm:
        raise AppError(ErrorCode.CONFIRMATION_REQUIRED)
    return Envelope(data={"deleted_count": await memory_service.delete_all(db, p.uid)})


@router.get("/messages/{message_id}/memories", tags=["memories"], operation_id="messages_memories")
async def message_memories(
    message_id: uuid.UUID, db: AsyncSession = Depends(get_db), p: Principal = Depends(require_user)
) -> ListEnvelope[dict[str, Any]]:
    msg = await message_service.get_owned(db, p.uid, message_id)
    ids = [uuid.UUID(i) for i in ((msg.metadata_ or {}).get("context") or {}).get("memory_ids", [])]
    if not ids:
        return ListEnvelope(data=[])
    from app.models import Memory

    rows = (
        (
            await db.execute(
                select(Memory).where(
                    Memory.id.in_(ids), Memory.user_id == p.uid, Memory.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    return ListEnvelope(data=[memory_service.memory_out(m) for m in rows])


# ------------------------------------------------------------------ tools / capabilities
@router.get("/tools", tags=["tools"], operation_id="tools_list")
async def tools(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(require_user)
) -> ListEnvelope[dict[str, Any]]:
    limits = await quota_service.plan_limits(db, p.plan_key)
    prefs = await user_service.get_preferences(db, p.uid)
    disabled = await settings_service.get(db, "disabled_tools")
    model = (
        get_registry().resolve(prefs.default_model_key)
        if prefs.default_model_key
        else get_registry().resolve(None)
    )
    out = []
    for t in tool_engine.registry().values():
        reason = tool_engine.disabled_reason(
            t,
            model=model,
            limits=limits,
            prefs=prefs,
            disabled_tools=disabled,
            has_files=True,
            toggles=None,
        )
        out.append(
            {
                "name": t.name,
                "display_name": t.display_name,
                "description": t.description,
                "enabled": reason is None,
                "disabled_reason": reason,
                "daily_limit": limits.get(t.quota_key) if t.quota_key else None,
            }
        )
    return ListEnvelope(data=out)


# ------------------------------------------------------------------ voice
@router.post(
    "/voice/transcriptions",
    tags=["voice"],
    operation_id="voice_transcribe",
    dependencies=[Depends(rate_limit("voice_transcribe"))],
)
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: str | None = Form(default=None, max_length=16),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("chat:write")),
) -> Envelope[dict[str, Any]]:
    data = await audio.read(voice_service.MAX_AUDIO_BYTES + 1)
    return Envelope(
        data=await voice_service.transcribe(
            db,
            p.uid,
            p.plan_key,
            data,
            audio.filename or "audio.webm",
            language,
            request_id(request),
        )
    )


class SpeechIn(In):
    message_id: uuid.UUID
    voice: str | None = Field(default=None, max_length=64)


@router.post(
    "/voice/speech",
    tags=["voice"],
    operation_id="voice_speech",
    dependencies=[Depends(rate_limit("voice_speech"))],
)
async def speech(
    body: SpeechIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Response:
    msg = await message_service.get_owned(db, p.uid, body.message_id)
    if msg.role != "assistant" or msg.status != "completed":
        raise AppError(ErrorCode.INVALID_MESSAGE_STATE)
    audio = await voice_service.synthesize(
        db, p.uid, p.plan_key, msg.content_text, body.voice, request_id(request)
    )
    return Response(audio, media_type="audio/mpeg")


# ------------------------------------------------------------------ reports
class ReportIn(In):
    category: Literal["abuse", "spam", "illegal", "self_harm", "harassment", "other"]
    details: str | None = Field(default=None, max_length=2000)


@router.post(
    "/messages/{message_id}/report",
    status_code=status.HTTP_201_CREATED,
    tags=["messages"],
    operation_id="messages_report",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def report(
    message_id: uuid.UUID,
    body: ReportIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Envelope[dict[str, str]]:
    msg = await message_service.get_owned(db, p.uid, message_id)
    flag = ModerationFlag(
        user_id=p.uid,
        conversation_id=msg.conversation_id,
        message_id=msg.id,
        source="user_report",
        category=body.category,
        details=body.details,
    )
    db.add(flag)
    await db.commit()
    return Envelope(data={"id": str(flag.id)})


# ------------------------------------------------------------------ API keys (session only)
class ApiKeyIn(In):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] | None = Field(default=None, max_length=7)
    expires_in_days: Literal[30, 90, 365] | None = None


class ApiKeyPatchIn(In):
    name: str = Field(min_length=1, max_length=80)


@router.get("/api-keys", tags=["api-keys"], operation_id="api_keys_list")
async def list_keys(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(require_user)
) -> ListEnvelope[dict[str, Any]]:
    if p.auth_method != "session":
        raise AppError(ErrorCode.FORBIDDEN)
    return ListEnvelope(
        data=[api_key_service.key_out(k) for k in await api_key_service.list_keys(db, p.uid)]
    )


@router.post(
    "/api-keys",
    status_code=status.HTTP_201_CREATED,
    tags=["api-keys"],
    operation_id="api_keys_create",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def create_key(
    body: ApiKeyIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(session_only),
) -> Envelope[dict[str, Any]]:
    return Envelope(
        data=await api_key_service.create(
            db,
            p.uid,
            p.plan_key,
            body.name,
            body.scopes,
            body.expires_in_days,
            request_id(request),
        )
    )


@router.patch("/api-keys/{key_id}", tags=["api-keys"], operation_id="api_keys_update")
async def rename_key(
    key_id: uuid.UUID,
    body: ApiKeyPatchIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(session_only),
) -> Envelope[dict[str, Any]]:
    return Envelope(
        data=api_key_service.key_out(await api_key_service.rename(db, p.uid, key_id, body.name))
    )


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["api-keys"],
    operation_id="api_keys_revoke",
)
async def revoke_key(
    key_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(session_only),
) -> Response:
    await api_key_service.revoke(db, p.uid, key_id, request_id(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ exports
class ExportIn(In):
    include_files: bool = True


@router.post(
    "/users/me/exports",
    status_code=status.HTTP_202_ACCEPTED,
    tags=["users"],
    operation_id="exports_create",
)
async def create_export(
    body: ExportIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(session_only),
) -> Envelope[dict[str, Any]]:
    e = await export_service.request_export(db, p.uid, body.include_files, request_id(request))
    return Envelope(data=export_service.export_out(e))


@router.get("/users/me/exports", tags=["users"], operation_id="exports_list")
async def list_exports(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(require_user)
) -> ListEnvelope[dict[str, Any]]:
    from app.models import DataExport

    rows = (
        (
            await db.execute(
                select(DataExport)
                .where(DataExport.user_id == p.uid)
                .order_by(DataExport.created_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    return ListEnvelope(data=[export_service.export_out(e) for e in rows])


@router.get(
    "/users/me/exports/{export_id}/download", tags=["users"], operation_id="exports_download"
)
async def download_export(
    export_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_user),
) -> RedirectResponse:
    url = await export_service.download(db, p.uid, export_id, request_id(request))
    return RedirectResponse(url, status_code=302)


__all__ = ["Message", "router"]
