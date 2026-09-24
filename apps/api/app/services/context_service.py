"""ContextService: builds the Groq message list within the token budget (docs/16).

Phase 2 scope: system prompt (+custom instructions), conversation summary, recent history and
the current user message. Memories (P7), RAG (P4) and tool results (P3) plug in later phases.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.ai.models_registry import ModelConfig
from app.ai.prompts import neutralize, render
from app.ai.provider import ImageInput, LLMMessage
from app.ai.tokens import estimate_message
from app.core.errors import AppError, ErrorCode
from app.models import Conversation, Message, UserPreferences

SYSTEM_CAP = 2500
SUMMARY_CAP = 1500


@dataclass
class TurnContext:
    conversation: Conversation
    path: list[Message]  # root → current user message (inclusive)
    model: ModelConfig
    preferences: UserPreferences
    plan_max_output_tokens: int
    tool_names: list[str] = field(default_factory=list)
    rag_block: str | None = None  # rendered <retrieved_documents> or a no-match note
    memory_block: str | None = None  # rendered <user_memories>
    images: list[ImageInput] = field(default_factory=list)  # current turn only


@dataclass
class BuiltContext:
    messages: list[LLMMessage]
    max_output_tokens: int
    estimated_prompt_tokens: int
    included_message_ids: list[uuid.UUID]
    summary_used: bool
    truncation: dict[str, Any]


def budget(model: ModelConfig, plan_max_output: int) -> tuple[int, int]:
    """Returns (prompt budget B, output tokens O) per docs/16 §4."""
    if not model.context_window:
        raise AppError(ErrorCode.MODEL_NOT_AVAILABLE)
    c = model.context_window
    o = min(model.default_max_output_tokens, plan_max_output)
    m = max(256, math.ceil(0.03 * c))
    return c - o - m, o


def _history_message(m: Message) -> LLMMessage | None:
    if m.role == "user":
        return LLMMessage(role="user", content=m.content_text)
    if m.role == "assistant":
        if m.status == "failed" and not m.content_text:
            return None
        text = m.content_text
        if m.status == "cancelled":
            text = f"{text}\n[response stopped by user]".strip()
        if (m.metadata_ or {}).get("tools_used"):
            text += f"\n[used tools: {', '.join(m.metadata_['tools_used'])}]"
        return LLMMessage(role="assistant", content=text) if text else None
    return None


def build(turn: TurnContext) -> BuiltContext:
    model, prefs = turn.model, turn.preferences
    bpt = model.token_estimate_bytes_per_token
    b, out_tokens = budget(model, turn.plan_max_output_tokens)
    tz = prefs.timezone or "UTC"
    try:
        today = datetime.now(ZoneInfo(tz)).strftime("%A, %d %B %Y")
    except Exception:
        today, tz = datetime.now(UTC).strftime("%A, %d %B %Y"), "UTC"
    system_text = render(
        "system_core.md",
        today=today,
        timezone=tz,
        tool_names=", ".join(turn.tool_names),
        custom_instructions=neutralize(prefs.custom_instructions or ""),
        about_user=neutralize(prefs.about_user or ""),
    )
    system = LLMMessage(role="system", content=system_text)
    current = turn.path[-1]
    current_msg = LLMMessage(role="user", content=current.content_text, images=tuple(turn.images))
    extras = [x for x in (turn.memory_block, turn.rag_block) if x]
    fixed = (
        estimate_message(system_text, bpt)
        + estimate_message(
            current.content_text, bpt, images=len(turn.images), image_cost=model.image_token_cost
        )
        + sum(estimate_message(x, bpt) for x in extras)
    )
    if estimate_message(system_text, bpt) > SYSTEM_CAP * 2 or fixed > b:
        raise AppError(ErrorCode.CONTEXT_TOO_LARGE)

    history = turn.path[:-1]
    remaining = b - fixed
    included: list[tuple[Message, LLMMessage]] = []
    for newest_rank, m in enumerate(reversed(history)):
        lm = _history_message(m)
        if lm is None:
            continue
        cost = estimate_message(lm.content, bpt)
        if cost <= remaining:
            included.append((m, lm))
            remaining -= cost
            continue
        if newest_rank < 2 and remaining > 200:
            # One of the last 2 messages is too big: keep it, truncated from the middle.
            half = int(remaining * bpt * 0.45)
            content = lm.content or ""
            included.append(
                (
                    m,
                    LLMMessage(
                        role=lm.role, content=content[:half] + "\n…[truncated]…\n" + content[-half:]
                    ),
                )
            )
            remaining = 0
        break
    included.reverse()
    omitted = len(history) - len(included)

    messages: list[LLMMessage] = [system]
    summary_used = False
    conv = turn.conversation
    history_ids = {m.id for m in history}
    if omitted and conv.summary and conv.summary_through_message_id in history_ids:
        s_cost = estimate_message(conv.summary, bpt)
        # drop oldest included messages until the summary fits
        while included and s_cost > remaining:
            m, lm = included.pop(0)
            remaining += estimate_message(lm.content, bpt)
        if s_cost <= remaining and s_cost <= SUMMARY_CAP * 2:
            messages.append(
                LLMMessage(
                    role="system",
                    content=f"<conversation_summary>\n{neutralize(conv.summary)}\n"
                    "</conversation_summary>",
                )
            )
            summary_used = True
            remaining -= s_cost
    messages += [lm for _, lm in included]
    messages += [LLMMessage(role="system", content=x) for x in extras]
    messages.append(current_msg)
    return BuiltContext(
        messages=messages,
        max_output_tokens=out_tokens,
        estimated_prompt_tokens=b - remaining,
        included_message_ids=[m.id for m, _ in included] + [current.id],
        summary_used=summary_used,
        truncation={"omitted_messages": omitted, "budget": b},
    )
