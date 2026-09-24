"""Conversation titles and rolling summaries via Groq (docs/11 §5, docs/16 §6)."""

from __future__ import annotations

import re
import uuid

import structlog
from sqlalchemy import select, update

from app.ai.groq.service import get_groq_service
from app.ai.models_registry import get_registry
from app.ai.provider import CallContext, ChatRequest, LLMMessage
from app.ai.tokens import estimate
from app.db.session import get_sessionmaker
from app.models import Conversation, Message
from app.services import context_service, message_service
from app.services.usage_service import record as record_usage

log = structlog.get_logger()
TITLE_PROMPT = (
    "Write a concise title (max 6 words) for this conversation. No quotes, no "
    "trailing punctuation, same language as the user. Respond with the title only."
)
SUMMARY_PROMPT = (
    "Summarize the conversation so far for continuity. Preserve: user goals, decisions, facts, "
    "names, numbers, code identifiers, open questions, and user preferences stated. At most 700 "
    "words. Neutral third person. Do not add information."
)


def clean_title(raw: str, fallback: str) -> str:
    t = re.sub(r"[`*_#>\"“”'‘’]", "", raw).replace("\n", " ")
    t = re.sub(r"\s+", " ", t).strip().rstrip(".!?:;")
    if len(t) > 60:
        t = t[:60].rsplit(" ", 1)[0]
    return t or fallback[:40].strip() or "New chat"


async def generate_title(conversation_id: uuid.UUID) -> str | None:
    async with get_sessionmaker()() as db:
        conv = await db.get(Conversation, conversation_id)
        if conv is None or conv.title_source != "default":
            return None
        rows = (
            (
                await db.execute(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at)
                    .limit(2)
                )
            )
            .scalars()
            .all()
        )
        user = next((m for m in rows if m.role == "user"), None)
        assistant = next((m for m in rows if m.role == "assistant"), None)
        if user is None:
            return None
        reg = get_registry()
        model = reg.for_purpose("title")
        convo = f"User: {user.content_text[:2000] or '(sent an attachment)'}\n\nAssistant: " + (
            assistant.content_text[:1000] if assistant else ""
        )
        result = await get_groq_service().complete(
            ChatRequest(
                model_key=model.key,
                purpose="title",
                temperature=0.3,
                max_output_tokens=24,
                messages=[
                    LLMMessage(role="system", content=TITLE_PROMPT),
                    LLMMessage(role="user", content=convo),
                ],
            ),
            ctx=CallContext(
                request_id=f"title:{conversation_id}",
                user_id=conv.user_id,
                conversation_id=conversation_id,
            ),
        )
        title = clean_title(result.text, user.content_text)
        res = await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.title_source == "default")
            .values(title=title, title_source="generated")
        )
        record_usage(
            db,
            kind="title",
            model=model,
            usage=result.usage,
            request_id=f"title:{conversation_id}",
            user_id=conv.user_id,
            latency_ms=result.latency_ms,
            conversation_id=conversation_id,
        )
        await db.commit()
        return title if res.rowcount else None  # type: ignore[attr-defined]


async def maybe_summarize(conversation_id: uuid.UUID) -> bool:
    async with get_sessionmaker()() as db:
        conv = await db.get(Conversation, conversation_id)
        if conv is None or conv.current_leaf_message_id is None:
            return False
        ids = await message_service.path_ids(db, conv.id, conv.current_leaf_message_id)
        path = await message_service.load_messages(db, ids)
        reg = get_registry()
        primary = reg.resolve(conv.model_key)
        budget, _ = context_service.budget(primary, 4096)
        total = sum(estimate(m.content_text) + 4 for m in path)
        if total < 0.6 * budget or len(path) < 8:
            return False
        keep, acc = [], 0
        for m in reversed(path):
            acc += estimate(m.content_text) + 4
            if acc > 0.4 * budget:
                break
            keep.append(m)
        old = path[: len(path) - len(keep)]
        if len(old) < 6:
            return False
        prior = ""
        if conv.summary and conv.summary_through_message_id in {m.id for m in old}:
            cut = [m.id for m in old].index(conv.summary_through_message_id)
            prior, old_tail = conv.summary, old[cut + 1 :]
        else:
            old_tail = old
        transcript = "\n\n".join(f"{m.role.title()}: {m.content_text}" for m in old_tail)
        model = reg.for_purpose("summary")
        content = (f"Existing summary:\n{prior}\n\n" if prior else "") + transcript
        result = await get_groq_service().complete(
            ChatRequest(
                model_key=model.key,
                purpose="summary",
                temperature=0.2,
                max_output_tokens=1200,
                messages=[
                    LLMMessage(role="system", content=SUMMARY_PROMPT),
                    LLMMessage(role="user", content=content[-60000:]),
                ],
            ),
            ctx=CallContext(
                request_id=f"summary:{conversation_id}",
                user_id=conv.user_id,
                conversation_id=conversation_id,
            ),
        )
        conv.summary = result.text.strip()
        conv.summary_through_message_id = old[-1].id
        conv.summary_token_count = estimate(conv.summary)
        record_usage(
            db,
            kind="summary",
            model=model,
            usage=result.usage,
            request_id=f"summary:{conversation_id}",
            user_id=conv.user_id,
            latency_ms=result.latency_ms,
            conversation_id=conversation_id,
        )
        await db.commit()
        log.info("conversation.summarized", conversation_id=str(conversation_id), covered=len(old))
        return True
