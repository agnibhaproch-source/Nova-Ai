"""Long-term memory: gated extraction, privacy filters, retrieval, user controls (docs/17)."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.groq.service import get_groq_service
from app.ai.models_registry import get_registry
from app.ai.prompts import neutralize
from app.ai.provider import CallContext, ChatRequest, LLMMessage
from app.ai.tokens import estimate
from app.core.errors import AppError, ErrorCode, not_found
from app.core.redis import get_redis, rkey
from app.db.session import get_sessionmaker
from app.embeddings.service import get_embeddings
from app.models import Memory, Message, UserPreferences
from app.services.usage_service import record as record_usage

log = structlog.get_logger("app.memory")
MAX_MEMORIES = 200
Category = Literal["preference", "biographical", "project", "instruction", "other"]

TRIGGERS = re.compile(
    r"\b(remember|don'?t forget|from now on|always|never|i prefer|i'?m an? |i am an? |i work|"
    r"my name is|call me|i'?m working on|i live|i like|i love|i hate|yaad rakh|mujhe pasand)\b",
    re.IGNORECASE,
)
SECRET_PATTERNS = [
    re.compile(p)
    for p in (
        r"nova_sk_[A-Za-z0-9]{8,}",
        r"\bsk-[A-Za-z0-9]{16,}",
        r"gsk_[A-Za-z0-9]{16,}",
        r"AKIA[0-9A-Z]{16}",
        r"eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}",
        r"-----BEGIN [A-Z ]+-----",
        r"\b[A-Z]{5}\d{4}[A-Z]\b",  # PAN
        r"\b\d{4}\s?\d{4}\s?\d{4}\b",  # Aadhaar-like
        r"\b(password|passcode|passwd|pin)\s*(is\b|[:=])",
    )
]
SENSITIVE_WORDS = re.compile(
    r"\b(diagnos|disease|illness|medication|depress|anxiety|hiv|cancer|pregnan|religio|"
    r"muslim|hindu|christian|sikh|jewish|political|vote[sd]? for|party member|gay|lesbian|"
    r"bisexual|transgender|sexual orientation|criminal|convicted|arrested)",
    re.IGNORECASE,
)
EXPLICIT = re.compile(r"\b(remember|don'?t forget|yaad rakh)\b", re.IGNORECASE)

EXTRACTION_PROMPT = """You maintain long-term memory for an assistant.
From the USER's messages only, propose memory operations. Save only information that is
(a) about the user, (b) likely useful in future conversations, (c) stable for weeks or longer,
and (d) either explicitly requested to be remembered or clearly volunteered as a preference,
standing instruction or ongoing project.
Never save: secrets, passwords, API keys, financial account numbers, government IDs, precise
addresses, health conditions, sexual orientation, religion, political views, criminal history, or
information about other people — unless the user explicitly asked you to remember it, and even
then never save secrets, credentials or ID numbers.
Do not save one-off task details, questions, or facts about the world.
Write memories in third person ("Prefers TypeScript examples").
Existing memories are listed; prefer "update" over near-duplicates; use "delete" if the user asked
to forget something.
Return JSON: {"operations":[{"op":"create"|"update"|"delete","memory_id":string|null,
"content":string|null,"category":"preference"|"biographical"|"project"|"instruction"|"other",
"importance":1-5,"explicit":true|false}]}
Return {"operations":[]} if nothing qualifies (this is the most common answer)."""


class MemoryOp(BaseModel):
    op: Literal["create", "update", "delete"]
    memory_id: str | None = None
    content: str | None = Field(default=None, max_length=500)
    category: Category = "other"
    importance: int = Field(default=3, ge=1, le=5)
    explicit: bool = False


class MemoryOps(BaseModel):
    operations: list[MemoryOp] = Field(default_factory=list, max_length=10)


def normalize(content: str) -> str:
    return re.sub(r"[^\w\s]", "", " ".join(content.lower().split()))


def content_hash(content: str) -> str:
    return hashlib.sha256(normalize(content).encode()).hexdigest()


def contains_secret(content: str) -> bool:
    return any(p.search(content) for p in SECRET_PATTERNS)


def should_extract(user_text: str) -> bool:
    return len(user_text) >= 20 and bool(TRIGGERS.search(user_text))


def memory_out(m: Memory) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "content": m.content,
        "category": m.category,
        "importance": m.importance,
        "source": m.source,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
        "last_used_at": m.last_used_at,
    }


async def _invalidate(user_id: uuid.UUID) -> None:
    try:
        await get_redis().delete(rkey("ctx", "mem", user_id))
    except Exception:
        pass


async def _embed(content: str) -> tuple[list[float] | None, str | None]:
    emb = get_embeddings()
    if not emb.available():
        return None, None
    try:
        return (await emb.embed_documents([content]))[0], emb.model_name
    except Exception:
        return None, None


# ------------------------------------------------------------------ user CRUD
async def list_memories(
    db: AsyncSession, user_id: uuid.UUID, q: str | None, category: str | None
) -> list[Memory]:
    stmt = select(Memory).where(Memory.user_id == user_id, Memory.deleted_at.is_(None))
    if q:
        stmt = stmt.where(Memory.content.ilike(f"%{q}%"))
    if category:
        stmt = stmt.where(Memory.category == category)
    return list(
        (await db.execute(stmt.order_by(Memory.updated_at.desc()).limit(500))).scalars().all()
    )


async def create(
    db: AsyncSession,
    user_id: uuid.UUID,
    content: str,
    category: str,
    importance: int,
    *,
    source: str = "user_created",
    conversation_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
) -> Memory:
    content = " ".join(content.split())
    if len(content) < 3 or contains_secret(content):
        raise AppError(ErrorCode.MEMORY_CONTENT_REJECTED)
    count = await db.scalar(
        select(func.count()).where(Memory.user_id == user_id, Memory.deleted_at.is_(None))
    )
    if (count or 0) >= MAX_MEMORIES:
        victim = await db.scalar(
            select(Memory)
            .where(
                Memory.user_id == user_id, Memory.deleted_at.is_(None), Memory.source == "extracted"
            )
            .order_by(Memory.importance, Memory.last_used_at.nulls_first())
            .limit(1)
        )
        if victim is None:
            raise AppError(ErrorCode.LIMIT_REACHED, "You've reached the memory limit.")
        victim.deleted_at = datetime.now(UTC)
    h = content_hash(content)
    existing = await db.scalar(
        select(Memory).where(
            Memory.user_id == user_id, Memory.content_hash == h, Memory.deleted_at.is_(None)
        )
    )
    if existing:
        return existing
    vec, model = await _embed(content)
    m = Memory(
        user_id=user_id,
        content=content,
        content_hash=h,
        category=category,
        importance=importance,
        source=source,
        source_conversation_id=conversation_id,
        source_message_id=message_id,
        embedding=vec,
        embedding_model=model,
    )
    db.add(m)
    await db.flush()
    await _invalidate(user_id)
    return m


async def get_owned(
    db: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID, include_deleted: bool = False
) -> Memory:
    stmt = select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
    if not include_deleted:
        stmt = stmt.where(Memory.deleted_at.is_(None))
    m = await db.scalar(stmt)
    if m is None:
        raise not_found()
    return m


async def update_memory(
    db: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID, fields: dict[str, Any]
) -> Memory:
    m = await get_owned(db, user_id, memory_id)
    if fields.get("content") is not None:
        c = " ".join(fields["content"].split())
        if len(c) < 3 or contains_secret(c):
            raise AppError(ErrorCode.MEMORY_CONTENT_REJECTED)
        m.content, m.content_hash = c, content_hash(c)
        m.embedding, m.embedding_model = await _embed(c)
    if fields.get("category"):
        m.category = fields["category"]
    if fields.get("importance"):
        m.importance = fields["importance"]
    await db.commit()
    await _invalidate(user_id)
    return m


async def delete_memory(db: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> None:
    m = await get_owned(db, user_id, memory_id)
    m.deleted_at = datetime.now(UTC)
    await db.commit()
    await _invalidate(user_id)


async def restore(db: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory:
    m = await get_owned(db, user_id, memory_id, include_deleted=True)
    if m.deleted_at and m.deleted_at < datetime.now(UTC) - timedelta(days=7):
        raise AppError(ErrorCode.RESTORE_WINDOW_EXPIRED)
    m.deleted_at = None
    await db.commit()
    await _invalidate(user_id)
    return m


async def delete_all(db: AsyncSession, user_id: uuid.UUID) -> int:
    res = await db.execute(
        update(Memory)
        .where(Memory.user_id == user_id, Memory.deleted_at.is_(None))
        .values(deleted_at=datetime.now(UTC))
    )
    await db.commit()
    await _invalidate(user_id)
    return int(res.rowcount)  # type: ignore[attr-defined]


# ------------------------------------------------------------------ retrieval
async def select_for_context(
    db: AsyncSession, user_id: uuid.UUID, query: str, budget_tokens: int
) -> tuple[str | None, list[uuid.UUID]]:
    prefs = await db.get(UserPreferences, user_id)
    if prefs is not None and not prefs.memory_enabled:
        return None, []
    always = list(
        (
            await db.execute(
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.deleted_at.is_(None),
                    Memory.category == "instruction",
                    Memory.importance >= 4,
                )
                .order_by(Memory.updated_at.desc())
                .limit(5)
            )
        )
        .scalars()
        .all()
    )
    scored: list[tuple[float, Memory]] = [(1.0, m) for m in always]
    emb = get_embeddings()
    qvec = await emb.embed_query(query) if emb.available() else None
    if qvec is not None:
        rows = (
            await db.execute(
                text(
                    "SELECT id, 1 - (embedding <=> CAST(:q AS vector)) AS sim FROM memories "
                    "WHERE user_id = :uid AND deleted_at IS NULL AND embedding IS NOT NULL "
                    "AND embedding_model = :model "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 30"
                ),
                {"q": str(qvec), "uid": user_id, "model": emb.model_name},
            )
        ).all()
        sims = {r.id: float(r.sim) for r in rows if float(r.sim) >= 0.35}
        if sims:
            mems = (await db.execute(select(Memory).where(Memory.id.in_(sims)))).scalars().all()
            scored += [(0.6 * sims[m.id] + 0.4 * m.importance / 5, m) for m in mems]
    else:
        # Without embeddings: include the most important memories (never guess relevance).
        top = (
            (
                await db.execute(
                    select(Memory)
                    .where(
                        Memory.user_id == user_id,
                        Memory.deleted_at.is_(None),
                        Memory.importance >= 3,
                    )
                    .order_by(Memory.importance.desc(), Memory.updated_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        scored += [(m.importance / 5, m) for m in top]
    seen: set[uuid.UUID] = set()
    lines: list[str] = []
    used: list[uuid.UUID] = []
    cost = 0
    for _, m in sorted(scored, key=lambda x: -x[0]):
        if m.id in seen or len(used) >= 15:
            continue
        seen.add(m.id)
        c = estimate(m.content) + 3
        if cost + c > budget_tokens:
            break
        cost += c
        lines.append(f"- {neutralize(m.content)}")
        used.append(m.id)
    if not used:
        return None, []
    await db.execute(
        update(Memory)
        .where(Memory.id.in_(used))
        .values(use_count=Memory.use_count + 1, last_used_at=datetime.now(UTC))
    )
    await db.commit()
    return "<user_memories>\n" + "\n".join(lines) + "\n</user_memories>", used


# ------------------------------------------------------------------ extraction job
async def extract_from_message(message_id: uuid.UUID) -> int:
    """Worker job: propose → validate → filter → dedupe → write (docs/17 §4)."""
    lock = rkey("memlock", str(message_id))
    sm = get_sessionmaker()
    async with sm() as db:
        assistant = await db.get(Message, message_id)
        if assistant is None or assistant.parent_message_id is None:
            return 0
        user_msg = await db.get(Message, assistant.parent_message_id)
        prefs = await db.get(UserPreferences, assistant.user_id)
        if user_msg is None or (prefs is not None and not prefs.memory_enabled):
            return 0
        from app.services import settings_service

        if not await settings_service.get(db, "memory_extraction_enabled"):
            return 0
        user_id = assistant.user_id
        existing = await list_memories(db, user_id, None, None)
    try:
        if not await get_redis().set(rkey("memlock", str(user_id)), "1", nx=True, ex=60):
            return 0
    except Exception:
        pass
    try:
        listing = "\n".join(f"{m.id}: {m.content}" for m in existing[:100]) or "(none)"
        model = get_registry().for_purpose("memory_extraction")
        ops = await get_groq_service().complete_json(
            ChatRequest(
                model_key=model.key,
                purpose="memory_extraction",
                temperature=0,
                max_output_tokens=600,
                messages=[
                    LLMMessage(role="system", content=EXTRACTION_PROMPT),
                    LLMMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "existing_memories": listing,
                                "user_message": user_msg.content_text[:4000],
                                "assistant_reply": assistant.content_text[:1500],
                            }
                        ),
                    ),
                ],
            ),
            MemoryOps,
            ctx=CallContext(
                request_id=f"memory:{message_id}",
                user_id=user_id,
                conversation_id=assistant.conversation_id,
                message_id=message_id,
            ),
        )
    finally:
        try:
            await get_redis().delete(lock)
        except Exception:
            pass
    explicit_intent = bool(EXPLICIT.search(user_msg.content_text))
    changed: list[str] = []
    async with sm() as db:
        own_ids = {str(m.id) for m in existing}
        for op in ops.operations[:3]:
            try:
                if op.op == "delete" and op.memory_id in own_ids:
                    m = await get_owned(db, user_id, uuid.UUID(op.memory_id))
                    m.deleted_at = datetime.now(UTC)
                    changed.append(str(m.id))
                    continue
                if not op.content or contains_secret(op.content):
                    log.info("memory.rejected", reason="secret_or_empty")
                    continue
                if SENSITIVE_WORDS.search(op.content) and not (op.explicit and explicit_intent):
                    log.info("memory.rejected", reason="sensitive_category")
                    continue
                if op.op == "update" and op.memory_id in own_ids:
                    m = await get_owned(db, user_id, uuid.UUID(op.memory_id))
                    m.content, m.content_hash = op.content, content_hash(op.content)
                    m.category, m.importance = op.category, op.importance
                    m.embedding, m.embedding_model = await _embed(op.content)
                    changed.append(str(m.id))
                elif op.op == "create":
                    m = await create(
                        db,
                        user_id,
                        op.content,
                        op.category,
                        max(op.importance, 4 if explicit_intent else 1),
                        source="extracted",
                        conversation_id=assistant.conversation_id,
                        message_id=user_msg.id,
                    )
                    changed.append(str(m.id))
            except AppError:
                continue
        record_usage(
            db,
            kind="memory_extraction",
            model=model,
            usage=None,
            request_id=f"memory:{message_id}",
            user_id=user_id,
            conversation_id=assistant.conversation_id,
            message_id=message_id,
        )
        await db.commit()
    if changed:
        await _invalidate(user_id)
        try:
            await get_redis().rpush(  # type: ignore[misc]
                rkey("notify", user_id),
                json.dumps(
                    {
                        "type": "memory_updated",
                        "memory_ids": changed,
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                ),
            )
            await get_redis().expire(rkey("notify", user_id), 600)
        except Exception:
            pass
    return len(changed)


async def pop_notifications(user_id: uuid.UUID) -> list[dict[str, Any]]:
    try:
        key = rkey("notify", user_id)
        items = await get_redis().lrange(key, 0, -1)  # type: ignore[misc]
        await get_redis().delete(key)
        return [json.loads(i) for i in items]
    except Exception:
        return []


async def decay() -> None:
    """Nightly: lower importance of unused extracted memories; retire stale ones (docs/17 §6)."""
    async with get_sessionmaker()() as db:
        cutoff = datetime.now(UTC) - timedelta(days=90)
        await db.execute(
            update(Memory)
            .where(
                Memory.source == "extracted",
                Memory.deleted_at.is_(None),
                Memory.importance > 1,
                func.coalesce(Memory.last_used_at, Memory.created_at) < cutoff,
            )
            .values(importance=Memory.importance - 1)
        )
        old = datetime.now(UTC) - timedelta(days=180)
        await db.execute(
            update(Memory)
            .where(
                Memory.source == "extracted",
                Memory.deleted_at.is_(None),
                func.coalesce(Memory.last_used_at, Memory.created_at) < old,
                (Memory.importance == 1) | (Memory.category == "project"),
            )
            .values(deleted_at=datetime.now(UTC))
        )
        await db.execute(text("DELETE FROM memories WHERE deleted_at < now() - interval '7 days'"))
        await db.commit()
