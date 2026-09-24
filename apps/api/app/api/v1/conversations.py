"""/api/v1/conversations* (docs/31 §5)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import Field, SecretStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.groq import keys as groq_keys
from app.ai.models_registry import get_registry
from app.api.deps import Principal, rate_limit, require_csrf, require_scopes
from app.core.errors import AppError, ErrorCode
from app.db.session import get_db
from app.schemas.common import Envelope, In, ListEnvelope, Page
from app.services import chat_service, conversation_service, message_service, quota_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


async def _allowed_models(db: AsyncSession, p: Principal) -> set[str]:
    limits = await quota_service.plan_limits(db, p.plan_key)
    return {m.key for m in get_registry().list_for_plan(p.plan_key, limits.get("models"))}


class ConversationCreateIn(In):
    model_key: str | None = Field(default=None, max_length=32)
    groq_api_key: SecretStr | None = None


class GroqKeyIn(In):
    api_key: SecretStr


class ConversationPatchIn(In):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None
    archived: bool | None = None
    model_key: str | None = Field(default=None, max_length=32)

    @field_validator("title")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return "".join(ch for ch in v if ord(ch) >= 32) if v else v


class BranchIn(In):
    message_id: uuid.UUID


class BulkDeleteIn(In):
    all: bool = False
    conversation_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


@router.get("", operation_id="conversations_list", dependencies=[Depends(rate_limit("api_read"))])
async def list_conversations(
    limit: int = Query(default=30, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=500),
    archived: bool = False,
    deleted: bool = False,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("conversations:read")),
) -> ListEnvelope[dict[str, Any]]:
    rows, nxt = await conversation_service.list_for_user(
        db, p.uid, limit=limit, cursor=cursor, archived=archived, deleted=deleted
    )
    return ListEnvelope(
        data=[conversation_service.to_out(c) for c in rows],
        page=Page(next_cursor=nxt, has_more=nxt is not None),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    operation_id="conversations_create",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def create_conversation(
    body: ConversationCreateIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("chat:write")),
) -> Envelope[dict[str, Any]]:
    allowed = await _allowed_models(db, p)
    from app.services import user_service

    prefs = await user_service.get_preferences(db, p.uid)
    key = body.model_key or prefs.default_model_key or get_registry().defaults.model_key
    if key not in allowed:
        if body.model_key:
            raise AppError(ErrorCode.MODEL_NOT_AVAILABLE)
        key = get_registry().defaults.model_key
    api_key = body.groq_api_key.get_secret_value().strip() if body.groq_api_key else None
    if groq_keys.user_mode():
        if not api_key:
            raise AppError(ErrorCode.GROQ_KEY_REQUIRED)
        await groq_keys.verify(api_key)
    conv = await conversation_service.create(db, p.uid, key)
    if groq_keys.user_mode() and api_key:
        await groq_keys.save(conv.id, api_key)
    return Envelope(data=conversation_service.to_out(conv))


@router.get(
    "/{conversation_id}/groq-key",
    operation_id="conversation_groq_key_status",
    dependencies=[Depends(rate_limit("api_read"))],
)
async def groq_key_status(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("conversations:read")),
) -> Envelope[dict[str, Any]]:
    await conversation_service.get_owned(db, p.uid, conversation_id)
    if not groq_keys.user_mode():
        return Envelope(data={"mode": "server", "configured": True, "expires_in_seconds": None})
    ttl = await groq_keys.ttl_seconds(conversation_id)
    return Envelope(data={"mode": "user", "configured": ttl is not None, "expires_in_seconds": ttl})


@router.put(
    "/{conversation_id}/groq-key",
    operation_id="conversation_groq_key_set",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def groq_key_set(
    conversation_id: uuid.UUID,
    body: GroqKeyIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("chat:write")),
) -> Envelope[dict[str, Any]]:
    await conversation_service.get_owned(db, p.uid, conversation_id)
    if not groq_keys.user_mode():
        raise AppError(ErrorCode.CONFLICT, "This deployment uses a server-managed key.")
    api_key = body.api_key.get_secret_value().strip()
    await groq_keys.verify(api_key)
    await groq_keys.save(conversation_id, api_key)
    ttl = await groq_keys.ttl_seconds(conversation_id)
    return Envelope(data={"mode": "user", "configured": True, "expires_in_seconds": ttl})


@router.delete(
    "/{conversation_id}/groq-key",
    status_code=204,
    operation_id="conversation_groq_key_delete",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def groq_key_delete(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Response:
    await conversation_service.get_owned(db, p.uid, conversation_id)
    await groq_keys.delete(conversation_id)
    return Response(status_code=204)


@router.get(
    "/search", operation_id="conversations_search", dependencies=[Depends(rate_limit("api_read"))]
)
async def search(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("conversations:read")),
) -> ListEnvelope[dict[str, Any]]:
    return ListEnvelope(data=await conversation_service.search(db, p.uid, q.strip(), limit))


@router.post(
    "/bulk-delete",
    operation_id="conversations_bulk_delete",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def bulk_delete(
    body: BulkDeleteIn, db: AsyncSession = Depends(get_db), p: Principal = Depends(require_csrf)
) -> Envelope[dict[str, int]]:
    if not body.all and not body.conversation_ids:
        raise AppError(ErrorCode.CONFIRMATION_REQUIRED)
    n = await conversation_service.bulk_delete(db, p.uid, body.conversation_ids, body.all)
    return Envelope(data={"deleted_count": n})


@router.get(
    "/{conversation_id}",
    operation_id="conversations_get",
    dependencies=[Depends(rate_limit("api_read"))],
)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("conversations:read")),
) -> Envelope[dict[str, Any]]:
    conv = await conversation_service.get_owned(db, p.uid, conversation_id, include_deleted=True)
    return Envelope(data=conversation_service.to_out(conv))


@router.patch(
    "/{conversation_id}",
    operation_id="conversations_update",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationPatchIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("conversations:write")),
) -> Envelope[dict[str, Any]]:
    fields = body.model_dump(exclude_unset=True)
    allowed = await _allowed_models(db, p) if fields.get("model_key") else set()
    conv = await conversation_service.update_fields(db, p.uid, conversation_id, fields, allowed)
    return Envelope(data=conversation_service.to_out(conv))


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="conversations_delete",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    permanent: bool = False,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("conversations:write")),
) -> Response:
    if permanent:
        await conversation_service.hard_delete(db, p.uid, conversation_id)
    else:
        conv = await conversation_service.soft_delete(db, p.uid, conversation_id)
        await chat_service.cancel_active_in_conversation(db, conv.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{conversation_id}/restore",
    operation_id="conversations_restore",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def restore(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Envelope[dict[str, Any]]:
    conv = await conversation_service.restore(db, p.uid, conversation_id)
    return Envelope(data=conversation_service.to_out(conv))


@router.post(
    "/{conversation_id}/branch",
    operation_id="conversations_branch",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def branch(
    conversation_id: uuid.UUID,
    body: BranchIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> ListEnvelope[dict[str, Any]]:
    conv = await conversation_service.switch_branch(db, p.uid, conversation_id, body.message_id)
    ids = await message_service.path_ids(db, conv.id, conv.current_leaf_message_id)
    msgs = await message_service.load_messages(db, ids)
    return ListEnvelope(
        data=await message_service.serialize(db, msgs),
        meta={"current_leaf_message_id": str(conv.current_leaf_message_id)},
    )
