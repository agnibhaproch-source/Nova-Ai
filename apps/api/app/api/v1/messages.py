"""Messages + streaming endpoints (docs/31 §6, docs/13)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, rate_limit, request_id, require_csrf, require_scopes
from app.core.errors import AppError, ErrorCode
from app.db.session import get_db, get_sessionmaker
from app.models import Message
from app.schemas.common import Envelope, In, ListEnvelope, Page
from app.services import chat_service, conversation_service, message_service
from app.services.chat_service import TurnResult
from app.streaming import runner
from app.streaming.sse import live_stream, resume_stream

router = APIRouter(tags=["messages"])
FEEDBACK_REASONS = Literal[
    "inaccurate",
    "not_helpful",
    "harmful",
    "incomplete",
    "wrong_citation",
    "too_long",
    "too_short",
    "other",
]


class ToolToggles(In):
    web_search: bool | None = None
    code_execution: bool | None = None


class SubmitIn(In):
    # May be empty when files are attached (e.g. just a screenshot).
    content: str = Field(default="", max_length=32000)
    parent_message_id: uuid.UUID | None = None
    model_key: str | None = Field(default=None, max_length=32)
    file_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    tools: ToolToggles | None = None


class RegenerateIn(In):
    model_key: str | None = Field(default=None, max_length=32)


class EditIn(In):
    content: str = Field(min_length=1, max_length=32000)


class FeedbackIn(In):
    rating: Literal["up", "down"]
    reasons: list[FEEDBACK_REASONS] = Field(default_factory=list, max_length=8)
    comment: str | None = Field(default=None, max_length=2000)


def _wants_sse(accept: str | None) -> bool:
    return accept is None or "text/event-stream" in accept or "application/json" not in accept


async def _respond(request: Request, turn: TurnResult, accept: str | None) -> Any:
    mid = turn.assistant_message.id
    if _wants_sse(accept):
        if turn.queue is not None:
            return live_stream(request, turn.queue, str(mid))
        return resume_stream(request, mid, 0)  # idempotent replay
    # Non-streaming mode (docs/05 §5.1)
    task = turn.task or runner.local_task(str(mid))
    if task is not None:
        await asyncio.wait_for(asyncio.shield(task), 300)
    else:
        for _ in range(240):
            async with get_sessionmaker()() as db:
                st = await db.scalar(select(Message.status).where(Message.id == mid))
            if st in message_service.TERMINAL:
                break
            await asyncio.sleep(0.5)
    async with get_sessionmaker()() as db:
        msgs = [
            m
            for m in [
                turn.user_message and await db.get(Message, turn.user_message.id),
                await db.get(Message, mid),
            ]
            if m is not None
        ]
        out = await message_service.serialize(db, msgs)
    data = {"user_message": out[0] if turn.user_message else None, "assistant_message": out[-1]}
    return JSONResponse(jsonable_encoder({"data": data}), status_code=200)


@router.get(
    "/conversations/{conversation_id}/messages",
    operation_id="messages_list",
    dependencies=[Depends(rate_limit("api_read"))],
)
async def list_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=100),
    before: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("conversations:read")),
) -> ListEnvelope[dict[str, Any]]:
    conv = await conversation_service.get_owned(db, p.uid, conversation_id, include_deleted=True)
    ids = await message_service.path_ids(db, conv.id, conv.current_leaf_message_id)
    if before is not None and before in ids:
        ids = ids[: ids.index(before)]
    has_more = len(ids) > limit
    page_ids = ids[-limit:]
    msgs = await message_service.load_messages(db, page_ids)
    active = next((m for m in reversed(msgs) if m.status in ("pending", "streaming")), None)
    return ListEnvelope(
        data=await message_service.serialize(db, msgs),
        page=Page(
            next_cursor=str(page_ids[0]) if has_more and page_ids else None, has_more=has_more
        ),
        meta={
            "current_leaf_message_id": str(conv.current_leaf_message_id)
            if conv.current_leaf_message_id
            else None,
            "active_generation_message_id": str(active.id) if active else None,
        },
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    operation_id="messages_create",
    dependencies=[Depends(rate_limit("chat_messages"))],
)
async def create_message(
    conversation_id: uuid.UUID,
    body: SubmitIn,
    request: Request,
    accept: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None, max_length=128),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("chat:write")),
) -> Any:
    content = body.content.strip()
    if not content and not body.file_ids:
        raise AppError(ErrorCode.VALIDATION_ERROR, details=[{"field": "content", "issue": "empty"}])
    toggles = {
        k: v for k, v in (body.tools.model_dump() if body.tools else {}).items() if v is not None
    }
    turn = await chat_service.submit(
        db,
        p,
        conversation_id,
        content=content,
        parent_message_id=body.parent_message_id,
        model_key=body.model_key,
        idempotency_key=idempotency_key,
        request_id=request_id(request),
        file_ids=body.file_ids,
        tools=toggles or None,
    )
    return await _respond(request, turn, accept)


@router.get(
    "/messages/{message_id}",
    operation_id="messages_get",
    dependencies=[Depends(rate_limit("api_read"))],
)
async def get_message(
    message_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("conversations:read")),
) -> Envelope[dict[str, Any]]:
    msg = await message_service.get_owned(db, p.uid, message_id)
    return Envelope(data=(await message_service.serialize(db, [msg]))[0])


@router.post(
    "/messages/{message_id}/regenerate",
    operation_id="messages_regenerate",
    dependencies=[Depends(rate_limit("chat_messages"))],
)
async def regenerate(
    message_id: uuid.UUID,
    body: RegenerateIn,
    request: Request,
    accept: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("chat:write")),
) -> Any:
    turn = await chat_service.regenerate(db, p, message_id, body.model_key, request_id(request))
    return await _respond(request, turn, accept)


@router.post(
    "/messages/{message_id}/edit",
    operation_id="messages_edit",
    dependencies=[Depends(rate_limit("chat_messages"))],
)
async def edit(
    message_id: uuid.UUID,
    body: EditIn,
    request: Request,
    accept: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("chat:write")),
) -> Any:
    turn = await chat_service.edit(db, p, message_id, body.content.strip(), request_id(request))
    return await _respond(request, turn, accept)


@router.post(
    "/messages/{message_id}/cancel",
    operation_id="messages_cancel",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def cancel(
    message_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Envelope[dict[str, str]]:
    state = await chat_service.cancel(db, p, message_id)
    response.status_code = status.HTTP_202_ACCEPTED if state == "cancelling" else 200
    return Envelope(data={"status": state})


@router.get(
    "/messages/{message_id}/stream",
    operation_id="messages_stream",
    dependencies=[Depends(rate_limit("stream_resume"))],
)
async def stream(
    message_id: uuid.UUID,
    request: Request,
    last_event_id_q: int | None = Query(default=None, alias="last_event_id", ge=0),
    last_event_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("chat:write")),
) -> Any:
    await message_service.get_owned(db, p.uid, message_id)
    after = (
        last_event_id_q
        if last_event_id_q is not None
        else int(last_event_id or 0)
        if (last_event_id or "0").isdigit()
        else 0
    )
    return resume_stream(request, message_id, after)


@router.put(
    "/messages/{message_id}/feedback",
    operation_id="messages_feedback_set",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def put_feedback(
    message_id: uuid.UUID,
    body: FeedbackIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Envelope[dict[str, Any]]:
    return Envelope(data=await chat_service.set_feedback(db, p, message_id, body.model_dump()))


@router.delete(
    "/messages/{message_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="messages_feedback_delete",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def delete_feedback(
    message_id: uuid.UUID, db: AsyncSession = Depends(get_db), p: Principal = Depends(require_csrf)
) -> Response:
    await chat_service.delete_feedback(db, p, message_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
