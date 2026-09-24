"""Internal messages/tools ↔ Groq OpenAI-compatible wire format (docs/14 §5.2)."""

from __future__ import annotations

from typing import Any

from app.ai.provider import LLMMessage, ResolvedChatRequest, ToolSchema
from app.core.errors import AppError, ErrorCode

# Sent in place of the text when a user sends only attachments (e.g. just a screenshot); the
# stored message stays empty, so the chat shows only the attachment.
ATTACHMENTS_ONLY_PROMPT = (
    "The user sent only the attached content, with no message. Look at it carefully and help "
    "with what it shows: answer the question or solve the problem in it, and if it contains "
    "code, explain it and give corrected or complete code."
)


def message_to_wire(m: LLMMessage, *, vision: bool) -> dict[str, Any] | None:
    if m.role == "user" and m.images:
        if not vision:
            raise AppError(ErrorCode.MODEL_CAPABILITY_MISSING)
        text = m.content if (m.content or "").strip() else ATTACHMENTS_ONLY_PROMPT
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
        parts += [{"type": "image_url", "image_url": {"url": i.data_url}} for i in m.images]
        return {"role": "user", "content": parts}
    if m.role == "assistant":
        if not m.content and not m.tool_calls:
            return None
        wire: dict[str, Any] = {"role": "assistant", "content": m.content or None}
        if m.tool_calls:
            wire["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments_json},
                }
                for c in m.tool_calls
            ]
        return wire
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""}
    if m.role == "user" and not (m.content or "").strip():
        return {"role": "user", "content": ATTACHMENTS_ONLY_PROMPT}
    return {"role": m.role, "content": m.content or ""}


def tool_to_wire(t: ToolSchema) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
    }


def build_params(r: ResolvedChatRequest, *, stream: bool, vision: bool) -> dict[str, Any]:
    req = r.request
    messages = [w for m in req.messages if (w := message_to_wire(m, vision=vision)) is not None]
    params: dict[str, Any] = {
        "model": r.groq_model_id,
        "messages": messages,
        "stream": stream,
        "temperature": r.temperature,
        "top_p": r.top_p,
        # verified in groq SDK 1.7: `max_completion_tokens` is accepted by chat.completions.create
        "max_completion_tokens": r.max_output_tokens,
        "stop": list(req.stop) or None,
        "seed": req.seed,
        "user": req.end_user_hash,
    }
    if req.tools and r.supports_tools and req.tool_choice != "none":
        params["tools"] = [tool_to_wire(t) for t in req.tools]
        params["tool_choice"] = req.tool_choice
        params["parallel_tool_calls"] = r.supports_parallel_tool_calls
    if req.json_mode and r.supports_json_mode:
        params["response_format"] = {"type": "json_object"}
    return {k: v for k, v in params.items() if v is not None}
