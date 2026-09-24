"""Message tree operations, persistence and serialization (docs/12)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ERROR_META, ErrorCode, not_found
from app.models import Feedback, Message, MessagePart

ALLOWED = {
    "pending": {"streaming", "completed", "cancelled", "failed"},
    "streaming": {"completed", "cancelled", "failed"},
}
TERMINAL = {"completed", "cancelled", "failed"}

PATH_SQL = text(
    """
    WITH RECURSIVE path AS (
      SELECT m.id, m.parent_message_id, 0 AS depth FROM messages m
       WHERE m.id = :leaf AND m.conversation_id = :cid
      UNION ALL
      SELECT p.id, p.parent_message_id, path.depth + 1 FROM messages p
        JOIN path ON p.id = path.parent_message_id
    )
    SELECT id FROM path ORDER BY depth DESC
    """
)


async def path_ids(
    db: AsyncSession, conversation_id: uuid.UUID, leaf_id: uuid.UUID | None
) -> list[uuid.UUID]:
    if leaf_id is None:
        return []
    rows = await db.execute(PATH_SQL, {"leaf": leaf_id, "cid": conversation_id})
    return [r[0] for r in rows]


async def load_messages(db: AsyncSession, ids: list[uuid.UUID]) -> list[Message]:
    if not ids:
        return []
    rows = (await db.execute(select(Message).where(Message.id.in_(ids)))).scalars().all()
    by_id = {m.id: m for m in rows}
    return [by_id[i] for i in ids if i in by_id]


async def get_owned(db: AsyncSession, user_id: uuid.UUID, message_id: uuid.UUID) -> Message:
    m = await db.scalar(select(Message).where(Message.id == message_id, Message.user_id == user_id))
    if m is None:
        raise not_found()
    return m


async def next_sibling_index(
    db: AsyncSession, conversation_id: uuid.UUID, parent_id: uuid.UUID | None
) -> int:
    cond = (
        (Message.parent_message_id == parent_id)
        if parent_id
        else (Message.parent_message_id.is_(None))
    )
    current = await db.scalar(
        select(func.max(Message.sibling_index)).where(
            Message.conversation_id == conversation_id, cond
        )
    )
    return 0 if current is None else int(current) + 1


def text_part(position: int, content: str) -> MessagePart:
    return MessagePart(position=position, type="text", text_content=content, data={})


async def transition(db: AsyncSession, message_id: uuid.UUID, to: str, **values: Any) -> bool:
    """Guarded status update: only moves forward from non-terminal states (docs/13 §9)."""
    froms = [s for s, targets in ALLOWED.items() if to in targets]
    res = await db.execute(
        update(Message)
        .where(Message.id == message_id, Message.status.in_(froms))
        .values(status=to, **values)
    )
    return bool(res.rowcount)  # type: ignore[attr-defined]


async def upsert_text_part(
    db: AsyncSession, message_id: uuid.UUID, position: int, content: str
) -> None:
    from sqlalchemy.dialects.postgresql import insert

    stmt = insert(MessagePart).values(
        message_id=message_id, position=position, type="text", text_content=content, data={}
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[MessagePart.message_id, MessagePart.position],
            set_={"text_content": content},
        )
    )


# ----------------------------------------------------------------- serialization
def part_out(p: MessagePart) -> dict[str, Any]:
    out: dict[str, Any] = {"id": str(p.id), "position": p.position, "type": p.type}
    if p.type in ("text", "code"):
        out["text"] = p.text_content or ""
    out.update(p.data or {})
    if p.file_id:
        out["file_id"] = str(p.file_id)
    if p.tool_call_id:
        out["tool_call_id"] = str(p.tool_call_id)
    return out


async def serialize(
    db: AsyncSession, messages: list[Message], *, with_siblings: bool = True
) -> list[dict[str, Any]]:
    if not messages:
        return []
    ids = [m.id for m in messages]
    parts = (
        (
            await db.execute(
                select(MessagePart)
                .where(MessagePart.message_id.in_(ids))
                .order_by(MessagePart.message_id, MessagePart.position)
            )
        )
        .scalars()
        .all()
    )
    parts_by: dict[uuid.UUID, list[MessagePart]] = {}
    for p in parts:
        parts_by.setdefault(p.message_id, []).append(p)
    fb = (await db.execute(select(Feedback).where(Feedback.message_id.in_(ids)))).scalars().all()
    fb_by = {f.message_id: f for f in fb}
    siblings: dict[uuid.UUID, dict[str, Any]] = {}
    if with_siblings:
        conv_id = messages[0].conversation_id
        parent_ids = {m.parent_message_id for m in messages}
        rows = (
            await db.execute(
                select(Message.id, Message.parent_message_id, Message.sibling_index)
                .where(Message.conversation_id == conv_id)
                .where(
                    (Message.parent_message_id.in_([p for p in parent_ids if p]))
                    | (Message.parent_message_id.is_(None))
                )
                .order_by(Message.sibling_index)
            )
        ).all()
        groups: dict[uuid.UUID | None, list[uuid.UUID]] = {}
        for r in rows:
            groups.setdefault(r.parent_message_id, []).append(r.id)
        for m in messages:
            group = groups.get(m.parent_message_id, [m.id])
            idx = group.index(m.id) if m.id in group else 0
            siblings[m.id] = {
                "index": idx,
                "count": len(group),
                "prev_id": str(group[idx - 1]) if idx > 0 else None,
                "next_id": str(group[idx + 1]) if idx + 1 < len(group) else None,
            }
    return [
        message_out(m, parts_by.get(m.id, []), fb_by.get(m.id), siblings.get(m.id))
        for m in messages
    ]


def message_out(
    m: Message,
    parts: list[MessagePart],
    feedback: Feedback | None = None,
    siblings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error = None
    if m.error_code:
        code = (
            ErrorCode(m.error_code)
            if m.error_code in ErrorCode.__members__
            else ErrorCode.INTERNAL_ERROR
        )
        error = {"code": m.error_code, "message": ERROR_META[code][2]}
    usage = None
    if m.role == "assistant" and m.prompt_tokens is not None:
        usage = {
            "prompt_tokens": m.prompt_tokens,
            "completion_tokens": m.completion_tokens,
            "time_to_first_token_ms": m.time_to_first_token_ms,
            "latency_ms": m.latency_ms,
        }
    return {
        "id": str(m.id),
        "conversation_id": str(m.conversation_id),
        "role": m.role,
        "status": m.status,
        "parent_message_id": str(m.parent_message_id) if m.parent_message_id else None,
        "created_at": m.created_at,
        "completed_at": m.completed_at,
        "model_key": m.model_key,
        "finish_reason": m.finish_reason,
        "error": error,
        "parts": [part_out(p) for p in sorted(parts, key=lambda p: p.position)],
        "siblings": siblings or {"index": 0, "count": 1, "prev_id": None, "next_id": None},
        "feedback": {
            "rating": feedback.rating,
            "reasons": feedback.reasons,
            "comment": feedback.comment,
        }
        if feedback
        else None,
        "usage": usage,
    }


def now() -> datetime:
    return datetime.now(UTC)
