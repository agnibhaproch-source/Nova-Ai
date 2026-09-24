"""Provider-neutral LLM types (docs/14 §3). Groq is the only implementation."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]
Purpose = Literal["chat", "title", "summary", "memory_extraction", "eval", "query_rewrite"]


@dataclass(frozen=True)
class ImageInput:
    data_url: str


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str | None = None
    images: tuple[ImageInput, ...] = ()
    tool_calls: tuple[LLMToolCall, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class ChatRequest:
    model_key: str
    messages: Sequence[LLMMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    tools: Sequence[ToolSchema] = ()
    tool_choice: Literal["auto", "none", "required"] = "auto"
    json_mode: bool = False
    stop: Sequence[str] = ()
    seed: int | None = None
    purpose: Purpose = "chat"
    end_user_hash: str | None = None


@dataclass(frozen=True)
class ResolvedChatRequest:
    request: ChatRequest
    groq_model_id: str
    temperature: float
    top_p: float
    max_output_tokens: int
    supports_tools: bool
    supports_json_mode: bool
    supports_parallel_tool_calls: bool


@dataclass
class ToolCallDelta:
    index: int
    id: str | None
    name: str | None
    arguments_fragment: str


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    queue_time_ms: int | None = None
    provider_total_time_ms: int | None = None


@dataclass
class ChatChunk:
    text_delta: str = ""
    tool_call_deltas: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage | None = None


@dataclass(frozen=True)
class ChatResult:
    text: str
    tool_calls: tuple[LLMToolCall, ...]
    finish_reason: str
    usage: Usage | None
    groq_model_id: str
    latency_ms: int


@dataclass(frozen=True)
class CallContext:
    request_id: str
    user_id: uuid.UUID | None
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    cancel_event: asyncio.Event | None = None


class ChatStream(Protocol):
    def __aiter__(self) -> AsyncIterator[ChatChunk]: ...
    async def aclose(self) -> None: ...


class LLMProvider(Protocol):
    async def open_stream(self, req: ResolvedChatRequest) -> ChatStream: ...
    async def complete(self, req: ResolvedChatRequest) -> ChatResult: ...
    async def list_models(self) -> dict[str, int | None]: ...
