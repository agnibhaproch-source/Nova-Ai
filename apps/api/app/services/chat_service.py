"""ChatService: turn orchestration (docs/11 §4, docs/12 §7–8)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.groq import keys as groq_keys
from app.ai.models_registry import get_registry
from app.api.deps import Principal
from app.core.errors import AppError, ErrorCode, not_found
from app.models import Conversation, Feedback, File, Message, MessagePart
from app.services import (
    analytics_service,
    file_service,
    message_service,
    quota_service,
    settings_service,
)
from app.streaming import runner
from app.streaming.broker import Event, broker


@dataclass
class TurnResult:
    user_message: Message | None
    assistant_message: Message
    created: bool  # False when an idempotent replay attached to an existing generation
    queue: asyncio.Queue[Event | None] | None = None  # local subscription (subscribed first)
    task: asyncio.Task[None] | None = None


async def _conversation(db: AsyncSession, user_id: uuid.UUID, cid: uuid.UUID) -> Conversation:
    conv = await db.scalar(
        select(Conversation).where(Conversation.id == cid, Conversation.user_id == user_id)
    )
    if conv is None:
        raise not_found()
    if conv.deleted_at is not None:
        raise AppError(ErrorCode.CONVERSATION_DELETED)
    return conv


async def _plan_models(db: AsyncSession, p: Principal) -> list[str]:
    limits = await quota_service.plan_limits(db, p.plan_key)
    return list(limits.get("models", []))


async def _resolve_model_key(
    db: AsyncSession, p: Principal, requested: str | None, fallback: str
) -> str:
    key = requested or fallback
    reg = get_registry()
    allowed = {m.key for m in reg.list_for_plan(p.plan_key, await _plan_models(db, p))}
    if key not in allowed:
        if requested:
            raise AppError(ErrorCode.MODEL_NOT_AVAILABLE)
        key = reg.defaults.model_key
    return key


async def _vision_if_needed(
    db: AsyncSession, p: Principal, key: str, file_ids: list[uuid.UUID]
) -> str:
    """Screenshots/photos go to a vision model for this turn when the chosen one can't see."""
    reg = get_registry()
    if not file_ids or reg.resolve(key).supports_vision:
        return key
    has_image = await db.scalar(
        select(func.count()).where(
            File.id.in_(file_ids), File.user_id == p.uid, File.kind == "image"
        )
    )
    if not has_image:
        return key
    allowed = reg.list_for_plan(p.plan_key, await _plan_models(db, p))
    vision = next((m.key for m in allowed if m.supports_vision and reg.is_enabled(m.key)), None)
    return vision or key  # _load_attachments then explains that no vision model is available


async def _preflight(
    db: AsyncSession, p: Principal, content_len: int, max_chars_key: str = "max_message_chars"
) -> None:
    if not await settings_service.get(db, "chat_enabled"):
        raise AppError(ErrorCode.SERVICE_DEGRADED, "Chat is temporarily unavailable.")
    limits = await quota_service.plan_limits(db, p.plan_key)
    if content_len > int(limits.get(max_chars_key, 32000)):
        raise AppError(
            ErrorCode.VALIDATION_ERROR,
            details=[
                {
                    "field": "content",
                    "issue": "too_long",
                    "message": f"Messages are limited to {limits.get(max_chars_key)} characters.",
                }
            ],
        )


async def _lock(conv_id: uuid.UUID, placeholder: uuid.UUID) -> None:
    if not await runner.acquire_conv_lock(conv_id, placeholder):
        raise AppError(ErrorCode.GENERATION_IN_PROGRESS)


async def _existing_by_idempotency(
    db: AsyncSession, conv_id: uuid.UUID, key: str | None, content: str
) -> TurnResult | None:
    if not key:
        return None
    user_msg = await db.scalar(
        select(Message).where(Message.conversation_id == conv_id, Message.idempotency_key == key)
    )
    if user_msg is None:
        return None
    if user_msg.content_text != content:
        raise AppError(ErrorCode.IDEMPOTENCY_KEY_REUSED)
    assistant = await db.scalar(
        select(Message)
        .where(Message.parent_message_id == user_msg.id)
        .order_by(Message.sibling_index.desc())
        .limit(1)
    )
    if assistant is None:
        raise not_found()
    return TurnResult(user_msg, assistant, created=False)


async def _create_turn(
    db: AsyncSession,
    p: Principal,
    conv: Conversation,
    *,
    parent_id: uuid.UUID | None,
    user_content: str | None,
    model_key: str,
    idempotency_key: str | None,
    regenerate_parent: Message | None = None,
    attachments: list[Any] | None = None,
) -> TurnResult:
    """Inserts (optional) user message + pending assistant message and moves the leaf."""
    user_msg: Message | None = None
    if user_content is not None:
        user_msg = Message(
            conversation_id=conv.id,
            user_id=p.uid,
            parent_message_id=parent_id,
            role="user",
            status="completed",
            content_text=user_content,
            idempotency_key=idempotency_key,
            sibling_index=await message_service.next_sibling_index(db, conv.id, parent_id),
        )
        db.add(user_msg)
        await db.flush()
        db.add(
            MessagePart(
                message_id=user_msg.id, position=0, type="text", text_content=user_content, data={}
            )
        )
        for i, f in enumerate(attachments or [], start=1):
            db.add(
                MessagePart(
                    message_id=user_msg.id,
                    position=i,
                    type="image" if f.kind == "image" else "file",
                    file_id=f.id,
                    data={
                        "filename": f.original_filename,
                        "mime_type": f.declared_mime_type,
                        "size_bytes": f.size_bytes,
                    },
                )
            )
            await file_service.attach(db, p.uid, conv.id, f.id, user_msg.id)
        anchor = user_msg
    else:
        assert regenerate_parent is not None
        anchor = regenerate_parent
    model = get_registry().resolve(model_key)
    assistant = Message(
        conversation_id=conv.id,
        user_id=p.uid,
        parent_message_id=anchor.id,
        role="assistant",
        status="pending",
        model_key=model.key,
        groq_model_id=model.groq_model_id,
        sibling_index=await message_service.next_sibling_index(db, conv.id, anchor.id),
    )
    db.add(assistant)
    await db.flush()
    conv.current_leaf_message_id = assistant.id
    conv.last_message_at = message_service.now()
    conv.message_count += 2 if user_msg else 1
    conv.model_key = model.key
    if conv.archived_at is not None:
        conv.archived_at = None
    return TurnResult(user_msg, assistant, created=True)


async def _start(
    db: AsyncSession,
    p: Principal,
    conv: Conversation,
    turn: TurnResult,
    request_id: str,
    *,
    is_edit: bool = False,
    is_regenerate: bool = False,
    tool_toggles: dict[str, bool] | None = None,
) -> None:
    first = conv.message_count <= 2 and conv.title_source == "default"
    await analytics_service.track(
        db,
        "message_sent",
        user_id=p.uid,
        properties={
            "model_key": turn.assistant_message.model_key,
            "has_attachments": bool(turn.user_message and turn.user_message.metadata_),
            "is_edit": is_edit,
            "is_regenerate": is_regenerate,
            "source": "api" if p.auth_method == "api_key" else "web",
            "char_count_bucket": analytics_service.char_bucket(
                len(turn.user_message.content_text) if turn.user_message else 0
            ),
        },
    )
    if first and not is_regenerate:
        await analytics_service.track(
            db,
            "chat_created",
            user_id=p.uid,
            properties={"model_key": conv.model_key, "source": "web"},
        )
    await db.commit()
    mid = str(turn.assistant_message.id)
    await broker.open(mid)
    turn.queue = broker.subscribe_local(mid)
    serialized = await message_service.serialize(
        db, [m for m in (turn.user_message, turn.assistant_message) if m is not None]
    )
    await broker.publish(
        mid,
        "message_start",
        {
            "conversation_id": str(conv.id),
            "user_message": serialized[0] if turn.user_message else None,
            "assistant_message": serialized[-1],
        },
    )
    turn.task = runner.start(
        runner.GenerationJob(
            assistant_message_id=turn.assistant_message.id,
            conversation_id=conv.id,
            user_id=p.uid,
            plan_key=p.plan_key,
            request_id=request_id,
            is_first_turn=first,
            is_edit=is_edit,
            is_regenerate=is_regenerate,
            tool_toggles=tool_toggles,
        )
    )


async def _load_attachments(
    db: AsyncSession, p: Principal, file_ids: list[uuid.UUID], model_key: str
) -> list[Any]:
    """Owned, usable files; images require a vision-capable model (docs/25 §3)."""
    if not file_ids:
        return []
    if len(file_ids) > 10:
        raise AppError(ErrorCode.LIMIT_REACHED, "Attach up to 10 files per message.")
    files = [await file_service.get_owned(db, p.uid, fid) for fid in dict.fromkeys(file_ids)]
    images = [f for f in files if f.kind == "image"]
    max_images = get_registry().resolve(model_key).max_images_per_request or 4
    if len(images) > max_images:
        raise AppError(ErrorCode.LIMIT_REACHED, f"Attach up to {max_images} images per message.")
    for f in files:
        if f.status in ("rejected", "failed", "pending_upload") or (
            f.kind == "image" and f.status != "ready"
        ):
            raise AppError(ErrorCode.FILE_NOT_READY)
    if images and not get_registry().resolve(model_key).supports_vision:
        raise AppError(
            ErrorCode.MODEL_CAPABILITY_MISSING,
            "The selected model can't read images. Choose a vision model.",
        )
    return files


async def submit(
    db: AsyncSession,
    p: Principal,
    conversation_id: uuid.UUID,
    *,
    content: str,
    parent_message_id: uuid.UUID | None,
    model_key: str | None,
    idempotency_key: str | None,
    request_id: str,
    file_ids: list[uuid.UUID] | None = None,
    tools: dict[str, bool] | None = None,
) -> TurnResult:
    conv = await _conversation(db, p.uid, conversation_id)
    await groq_keys.for_conversation(conv.id)
    if existing := await _existing_by_idempotency(db, conv.id, idempotency_key, content):
        return existing
    await _preflight(db, p, len(content))
    parent_id = parent_message_id if parent_message_id is not None else conv.current_leaf_message_id
    if parent_id is not None:
        parent = await db.scalar(
            select(Message).where(Message.id == parent_id, Message.conversation_id == conv.id)
        )
        if parent is None:
            raise not_found()
        if parent.role != "assistant" or parent.status not in message_service.TERMINAL:
            raise AppError(ErrorCode.INVALID_MESSAGE_STATE)
    key = await _resolve_model_key(db, p, model_key, conv.model_key)
    key = await _vision_if_needed(db, p, key, file_ids or [])
    attachments = await _load_attachments(db, p, file_ids or [], key)
    placeholder = uuid.uuid4()
    await _lock(conv.id, placeholder)
    try:
        turn = await _create_turn(
            db,
            p,
            conv,
            parent_id=parent_id,
            user_content=content,
            model_key=key,
            idempotency_key=idempotency_key,
            attachments=attachments,
        )
        await _start(db, p, conv, turn, request_id, tool_toggles=tools)
    except BaseException:
        await runner.release_conv_lock(conv.id)
        raise
    return turn


async def regenerate(
    db: AsyncSession, p: Principal, message_id: uuid.UUID, model_key: str | None, request_id: str
) -> TurnResult:
    msg = await message_service.get_owned(db, p.uid, message_id)
    if msg.role != "assistant" or msg.status not in message_service.TERMINAL:
        raise AppError(ErrorCode.INVALID_MESSAGE_STATE)
    conv = await _conversation(db, p.uid, msg.conversation_id)
    await groq_keys.for_conversation(conv.id)
    parent = await db.get(Message, msg.parent_message_id)
    assert parent is not None
    await _preflight(db, p, len(parent.content_text))
    key = await _resolve_model_key(db, p, model_key, msg.model_key or conv.model_key)
    await _lock(conv.id, msg.id)
    try:
        turn = await _create_turn(
            db,
            p,
            conv,
            parent_id=None,
            user_content=None,
            model_key=key,
            idempotency_key=None,
            regenerate_parent=parent,
        )
        await _start(db, p, conv, turn, request_id, is_regenerate=True)
    except BaseException:
        await runner.release_conv_lock(conv.id)
        raise
    return turn


async def edit(
    db: AsyncSession, p: Principal, message_id: uuid.UUID, content: str, request_id: str
) -> TurnResult:
    msg = await message_service.get_owned(db, p.uid, message_id)
    if msg.role != "user":
        raise AppError(ErrorCode.INVALID_MESSAGE_STATE)
    conv = await _conversation(db, p.uid, msg.conversation_id)
    await groq_keys.for_conversation(conv.id)
    await _preflight(db, p, len(content))
    key = await _resolve_model_key(db, p, None, conv.model_key)
    await _lock(conv.id, msg.id)
    try:
        turn = await _create_turn(
            db,
            p,
            conv,
            parent_id=msg.parent_message_id,
            user_content=content,
            model_key=key,
            idempotency_key=None,
        )
        await _start(db, p, conv, turn, request_id, is_edit=True)
    except BaseException:
        await runner.release_conv_lock(conv.id)
        raise
    return turn


async def cancel(db: AsyncSession, p: Principal, message_id: uuid.UUID) -> str:
    msg = await message_service.get_owned(db, p.uid, message_id)
    if msg.status in message_service.TERMINAL:
        return msg.status
    await broker.request_cancel(str(msg.id))
    return "cancelling"


async def cancel_active_in_conversation(db: AsyncSession, conv_id: uuid.UUID) -> None:
    rows = (
        (
            await db.execute(
                select(Message.id).where(
                    Message.conversation_id == conv_id, Message.status.in_(("pending", "streaming"))
                )
            )
        )
        .scalars()
        .all()
    )
    for mid in rows:
        await broker.request_cancel(str(mid))


async def set_feedback(
    db: AsyncSession, p: Principal, message_id: uuid.UUID, data: dict[str, Any]
) -> dict[str, Any]:
    msg = await message_service.get_owned(db, p.uid, message_id)
    if msg.role != "assistant" or msg.status not in message_service.TERMINAL:
        raise AppError(ErrorCode.INVALID_MESSAGE_STATE)
    values = {
        "user_id": p.uid,
        "message_id": msg.id,
        "conversation_id": msg.conversation_id,
        "rating": data["rating"],
        "reasons": data.get("reasons") or [],
        "comment": data.get("comment"),
    }
    stmt = insert(Feedback).values(**values)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[Feedback.user_id, Feedback.message_id],
            set_={k: values[k] for k in ("rating", "reasons", "comment")},
        )
    )
    await analytics_service.track(
        db,
        "feedback_given",
        user_id=p.uid,
        properties={"rating": data["rating"], "reasons": data.get("reasons") or []},
    )
    await db.commit()
    return {"rating": values["rating"], "reasons": values["reasons"], "comment": values["comment"]}


async def delete_feedback(db: AsyncSession, p: Principal, message_id: uuid.UUID) -> None:
    await message_service.get_owned(db, p.uid, message_id)
    await db.execute(
        delete(Feedback).where(Feedback.user_id == p.uid, Feedback.message_id == message_id)
    )
    await db.commit()
