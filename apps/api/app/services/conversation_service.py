"""Conversation CRUD, listing (keyset), search, trash, branch switching (docs/11)."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, not_found
from app.core.security import b64url, constant_time_eq, hmac_sha256
from app.models import Conversation, Message

MAX_PINNED = 20
TRASH_DAYS = 30


# ---------------------------------------------------------------- cursors (signed)
def encode_cursor(payload: dict[str, Any]) -> str:
    raw = b64url(json.dumps(payload, separators=(",", ":"), default=str).encode())
    return f"{raw}.{b64url(hmac_sha256('cursor:' + raw))[:16]}"


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        raw, sig = cursor.split(".", 1)
        if not constant_time_eq(sig, b64url(hmac_sha256("cursor:" + raw))[:16]):
            raise ValueError
        padded = raw + "=" * (-len(raw) % 4)
        return dict(json.loads(base64.urlsafe_b64decode(padded)))
    except (ValueError, json.JSONDecodeError) as e:
        raise AppError(ErrorCode.INVALID_CURSOR) from e


# ---------------------------------------------------------------- queries
async def get_owned(
    db: AsyncSession, user_id: uuid.UUID, cid: uuid.UUID, *, include_deleted: bool = False
) -> Conversation:
    q = select(Conversation).where(Conversation.id == cid, Conversation.user_id == user_id)
    if not include_deleted:
        q = q.where(Conversation.deleted_at.is_(None))
    conv = await db.scalar(q)
    if conv is None:
        raise not_found()
    return conv


async def create(db: AsyncSession, user_id: uuid.UUID, model_key: str) -> Conversation:
    conv = Conversation(user_id=user_id, model_key=model_key)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def list_for_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int,
    cursor: str | None,
    archived: bool,
    deleted: bool,
) -> tuple[list[Conversation], str | None]:
    q = select(Conversation).where(Conversation.user_id == user_id)
    if deleted:
        q = q.where(Conversation.deleted_at.is_not(None)).order_by(
            Conversation.deleted_at.desc(), Conversation.id.desc()
        )
        if cursor:
            c = decode_cursor(cursor)
            t, cid = datetime.fromisoformat(c["t"]), uuid.UUID(c["id"])
            q = q.where(
                or_(
                    Conversation.deleted_at < t,
                    and_(Conversation.deleted_at == t, Conversation.id < cid),
                )
            )
    else:
        q = q.where(Conversation.deleted_at.is_(None), Conversation.message_count > 0)
        q = q.where(
            Conversation.archived_at.is_not(None)
            if archived
            else Conversation.archived_at.is_(None)
        )
        # pinned first, then last activity. Encode pinned as a sortable epoch (0 = unpinned).
        pin_key = func.coalesce(func.extract("epoch", Conversation.pinned_at), 0)
        q = q.order_by(pin_key.desc(), Conversation.last_message_at.desc(), Conversation.id.desc())
        if cursor:
            c = decode_cursor(cursor)
            p, t, cid = float(c["p"]), datetime.fromisoformat(c["t"]), uuid.UUID(c["id"])
            q = q.where(
                or_(
                    pin_key < p,
                    and_(
                        pin_key == p,
                        or_(
                            Conversation.last_message_at < t,
                            and_(Conversation.last_message_at == t, Conversation.id < cid),
                        ),
                    ),
                )
            )
    rows = list((await db.execute(q.limit(limit + 1))).scalars().all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        if deleted:
            next_cursor = encode_cursor({"t": last.deleted_at, "id": str(last.id)})
        else:
            p = last.pinned_at.timestamp() if last.pinned_at else 0
            next_cursor = encode_cursor({"p": p, "t": last.last_message_at, "id": str(last.id)})
    return rows, next_cursor


async def update_fields(
    db: AsyncSession,
    user_id: uuid.UUID,
    cid: uuid.UUID,
    fields: dict[str, Any],
    allowed_models: set[str],
) -> Conversation:
    conv = await get_owned(db, user_id, cid)
    now = datetime.now(UTC)
    if "title" in fields and fields["title"] is not None:
        conv.title = fields["title"]
        conv.title_source = "user"
    if "pinned" in fields and fields["pinned"] is not None:
        if fields["pinned"] and conv.pinned_at is None:
            pinned = await db.scalar(
                select(func.count()).where(
                    Conversation.user_id == user_id,
                    Conversation.pinned_at.is_not(None),
                    Conversation.deleted_at.is_(None),
                )
            )
            if (pinned or 0) >= MAX_PINNED:
                raise AppError(ErrorCode.LIMIT_REACHED, "You can pin up to 20 conversations.")
            conv.pinned_at = now
        elif not fields["pinned"]:
            conv.pinned_at = None
    if "archived" in fields and fields["archived"] is not None:
        conv.archived_at = now if fields["archived"] else None
        if fields["archived"]:
            conv.pinned_at = None
    if fields.get("model_key") is not None:
        if fields["model_key"] not in allowed_models:
            raise AppError(ErrorCode.MODEL_NOT_AVAILABLE)
        conv.model_key = fields["model_key"]
    await db.commit()
    await db.refresh(conv)
    return conv


async def soft_delete(db: AsyncSession, user_id: uuid.UUID, cid: uuid.UUID) -> Conversation:
    conv = await get_owned(db, user_id, cid)
    conv.deleted_at = datetime.now(UTC)
    await db.commit()
    return conv


async def hard_delete(db: AsyncSession, user_id: uuid.UUID, cid: uuid.UUID) -> None:
    conv = await get_owned(db, user_id, cid, include_deleted=True)
    if conv.deleted_at is None:
        raise AppError(ErrorCode.NOT_IN_TRASH)
    await _hard_delete_ids(db, [conv.id])
    await db.commit()


async def _hard_delete_ids(db: AsyncSession, ids: list[uuid.UUID]) -> None:
    if not ids:
        return
    # Break the conversation→message FKs first, then cascade.
    await db.execute(
        update(Conversation)
        .where(Conversation.id.in_(ids))
        .values(current_leaf_message_id=None, summary_through_message_id=None)
    )
    await db.execute(delete(Conversation).where(Conversation.id.in_(ids)))


async def restore(db: AsyncSession, user_id: uuid.UUID, cid: uuid.UUID) -> Conversation:
    conv = await get_owned(db, user_id, cid, include_deleted=True)
    if conv.deleted_at is None:
        return conv
    if conv.deleted_at < datetime.now(UTC) - timedelta(days=TRASH_DAYS):
        raise AppError(ErrorCode.RESTORE_WINDOW_EXPIRED)
    conv.deleted_at = None
    await db.commit()
    await db.refresh(conv)
    return conv


async def bulk_delete(
    db: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID] | None, all_: bool
) -> int:
    q = update(Conversation).where(
        Conversation.user_id == user_id, Conversation.deleted_at.is_(None)
    )
    if not all_:
        q = q.where(Conversation.id.in_(ids or []))
    res = await db.execute(q.values(deleted_at=datetime.now(UTC)))
    await db.commit()
    return int(res.rowcount)  # type: ignore[attr-defined]


SEARCH_SQL = text(
    """
    WITH q AS (SELECT websearch_to_tsquery('simple', :q) AS query),
    msg AS (
      SELECT DISTINCT ON (m.conversation_id) m.conversation_id, m.id AS message_id,
             ts_rank_cd(m.content_tsv, q.query) AS rank,
             ts_headline('simple', left(m.content_text, 5000), q.query,
                'StartSel=<<,StopSel=>>,MaxWords=18,MinWords=8,MaxFragments=1') AS snippet
        FROM messages m JOIN conversations c ON c.id = m.conversation_id, q
       WHERE m.user_id = :uid AND c.user_id = :uid AND c.deleted_at IS NULL
         AND m.role IN ('user','assistant') AND m.content_tsv @@ q.query
       ORDER BY m.conversation_id, rank DESC
    ),
    ttl AS (
      SELECT c.id AS conversation_id FROM conversations c
       WHERE c.user_id = :uid AND c.deleted_at IS NULL AND c.message_count > 0
         AND (c.title ILIKE '%' || :q || '%' OR similarity(c.title, :q) > 0.3)
    )
    SELECT c.id, c.title, c.last_message_at, msg.message_id, msg.snippet,
           COALESCE(msg.rank, 0) + CASE WHEN ttl.conversation_id IS NOT NULL THEN 0.5 ELSE 0 END
             AS score
      FROM conversations c
      LEFT JOIN msg ON msg.conversation_id = c.id
      LEFT JOIN ttl ON ttl.conversation_id = c.id
     WHERE c.user_id = :uid AND (msg.conversation_id IS NOT NULL OR ttl.conversation_id IS NOT NULL)
     ORDER BY score DESC, c.last_message_at DESC
     LIMIT :limit
    """
)


async def search(db: AsyncSession, user_id: uuid.UUID, q: str, limit: int) -> list[dict[str, Any]]:
    rows = (await db.execute(SEARCH_SQL, {"q": q, "uid": user_id, "limit": limit})).all()
    out = []
    for r in rows:
        snippet, highlights = _parse_snippet(r.snippet or "")
        out.append(
            {
                "conversation_id": str(r.id),
                "title": r.title,
                "message_id": str(r.message_id) if r.message_id else None,
                "snippet": snippet or None,
                "highlights": highlights,
                "last_message_at": r.last_message_at,
            }
        )
    return out


def _parse_snippet(s: str) -> tuple[str, list[list[int]]]:
    out, highlights, i = "", [], 0
    while i < len(s):
        if s.startswith("<<", i):
            end = s.find(">>", i)
            if end == -1:
                break
            word = s[i + 2 : end]
            highlights.append([len(out), len(out) + len(word)])
            out += word
            i = end + 2
        else:
            out += s[i]
            i += 1
    return out, highlights


BRANCH_SQL = text(
    """
    WITH RECURSIVE sub AS (
      SELECT id, created_at FROM messages WHERE id = :mid AND conversation_id = :cid
      UNION ALL
      SELECT m.id, m.created_at FROM messages m JOIN sub ON m.parent_message_id = sub.id
    )
    SELECT s.id FROM sub s
     WHERE NOT EXISTS (SELECT 1 FROM messages c WHERE c.parent_message_id = s.id)
     ORDER BY s.created_at DESC LIMIT 1
    """
)


async def switch_branch(
    db: AsyncSession, user_id: uuid.UUID, cid: uuid.UUID, message_id: uuid.UUID
) -> Conversation:
    conv = await get_owned(db, user_id, cid)
    msg = await db.scalar(
        select(Message.id).where(Message.id == message_id, Message.conversation_id == conv.id)
    )
    if msg is None:
        raise not_found()
    leaf = await db.scalar(BRANCH_SQL, {"mid": message_id, "cid": conv.id})
    conv.current_leaf_message_id = leaf
    await db.commit()
    return conv


def to_out(c: Conversation) -> dict[str, Any]:
    purge_at = c.deleted_at + timedelta(days=TRASH_DAYS) if c.deleted_at else None
    return {
        "id": str(c.id),
        "title": c.title,
        "title_source": c.title_source,
        "model_key": c.model_key,
        "pinned": c.pinned_at is not None,
        "archived": c.archived_at is not None,
        "deleted_at": c.deleted_at,
        "purge_at": purge_at,
        "current_leaf_message_id": str(c.current_leaf_message_id)
        if c.current_leaf_message_id
        else None,
        "last_message_at": c.last_message_at,
        "created_at": c.created_at,
        "message_count": c.message_count,
    }
