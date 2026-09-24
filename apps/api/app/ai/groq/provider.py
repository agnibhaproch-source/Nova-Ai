"""GroqProvider: the only code that calls the Groq SDK (docs/14)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

import groq
import httpx
from groq import AsyncGroq

from app.ai.groq import keys as groq_keys
from app.ai.groq.converters import build_params
from app.ai.groq.errors import map_groq_error
from app.ai.provider import (
    ChatChunk,
    ChatResult,
    LLMToolCall,
    ResolvedChatRequest,
    ToolCallDelta,
    Usage,
)
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode


def get_groq_client() -> AsyncGroq:
    """Client for the key in scope: the conversation owner's key (BYOK) or the server key."""
    user_key = groq_keys.current()
    if user_key is not None:
        return _client_for(user_key)
    s = get_settings()
    if s.GROQ_API_KEY is None or s.GROQ_KEY_MODE == "user":
        raise AppError(ErrorCode.GROQ_KEY_REQUIRED)
    return _client_for(s.GROQ_API_KEY.get_secret_value())


@lru_cache(maxsize=256)
def _client_for(api_key: str) -> AsyncGroq:
    s = get_settings()
    return AsyncGroq(
        api_key=api_key,
        base_url=s.groq_base_url,  # explicit so the SDK never reads GROQ_BASE_URL itself
        max_retries=0,  # retries are owned by GroqService
        timeout=httpx.Timeout(connect=5.0, read=s.GROQ_TIMEOUT_SECONDS, write=10.0, pool=5.0),
        http_client=_http_client_override or _shared_http(),
    )


@lru_cache
def _shared_http() -> httpx.AsyncClient:
    # One connection pool for all keys; the key is only an Authorization header.
    return httpx.AsyncClient(limits=httpx.Limits(max_connections=200, max_keepalive_connections=50))


_http_client_override: httpx.AsyncClient | None = None


def set_http_client_override(client: httpx.AsyncClient | None) -> None:
    """Test hook: inject an httpx client (e.g. MockTransport). Never used in production code."""
    global _http_client_override
    _http_client_override = client
    _client_for.cache_clear()


def _usage(obj: Any) -> Usage | None:
    u = getattr(obj, "usage", None)
    if u is None:
        xg = getattr(obj, "x_groq", None)
        u = getattr(xg, "usage", None) if xg is not None else None
    if u is None:
        return None
    qt = getattr(u, "queue_time", None)
    tt = getattr(u, "total_time", None)
    return Usage(
        prompt_tokens=int(u.prompt_tokens or 0),
        completion_tokens=int(u.completion_tokens or 0),
        total_tokens=int(u.total_tokens or 0),
        queue_time_ms=int(qt * 1000) if qt else None,
        provider_total_time_ms=int(tt * 1000) if tt else None,
    )


class GroqChatStream:
    def __init__(self, stream: Any) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[ChatChunk]:
        try:
            async for raw in self._stream:
                chunk = ChatChunk(usage=_usage(raw))
                if raw.choices:
                    choice = raw.choices[0]
                    delta = choice.delta
                    chunk.text_delta = (delta.content or "") if delta else ""
                    for tc in (delta.tool_calls or []) if delta else []:
                        fn = tc.function
                        chunk.tool_call_deltas.append(
                            ToolCallDelta(
                                index=tc.index,
                                id=tc.id,
                                name=fn.name if fn else None,
                                arguments_fragment=(fn.arguments or "") if fn else "",
                            )
                        )
                    chunk.finish_reason = choice.finish_reason
                yield chunk
        except groq.GroqError as e:
            raise map_groq_error(e) from e

    async def aclose(self) -> None:
        await self._stream.close()


def _is_vision(groq_model_id: str) -> bool:
    from app.ai.models_registry import get_registry

    return any(m.groq_model_id == groq_model_id and m.supports_vision for m in get_registry().all())


class GroqProvider:
    async def open_stream(self, req: ResolvedChatRequest) -> GroqChatStream:
        params = build_params(req, stream=True, vision=_is_vision(req.groq_model_id))
        try:
            stream = await get_groq_client().chat.completions.create(**params)
        except groq.GroqError as e:
            raise map_groq_error(e) from e
        return GroqChatStream(stream)

    async def complete(self, req: ResolvedChatRequest) -> ChatResult:
        params = build_params(req, stream=False, vision=_is_vision(req.groq_model_id))
        started = time.perf_counter()
        try:
            resp = await get_groq_client().chat.completions.create(**params)
        except groq.GroqError as e:
            raise map_groq_error(e) from e
        choice = resp.choices[0]
        calls = tuple(
            LLMToolCall(id=c.id, name=c.function.name, arguments_json=c.function.arguments)
            for c in (choice.message.tool_calls or [])
        )
        return ChatResult(
            text=choice.message.content or "",
            tool_calls=calls,
            finish_reason=choice.finish_reason or "stop",
            usage=_usage(resp),
            groq_model_id=req.groq_model_id,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def list_models(self) -> dict[str, int | None]:
        try:
            page = await get_groq_client().models.list()
        except groq.GroqError as e:
            raise map_groq_error(e) from e
        out: dict[str, int | None] = {}
        for m in page.data:
            cw = getattr(m, "context_window", None)
            out[m.id] = int(cw) if isinstance(cw, int) else None
        return out

    async def transcribe(
        self, audio: bytes, filename: str, model_id: str, language: str | None
    ) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": model_id,
            "file": (filename, audio),
            "response_format": "verbose_json",
        }
        if language:
            kwargs["language"] = language
        try:
            res = await get_groq_client().audio.transcriptions.create(**kwargs)  # type: ignore[arg-type]
        except groq.GroqError as e:
            raise map_groq_error(e) from e
        return {
            "text": getattr(res, "text", "") or "",
            "language": getattr(res, "language", None),
            "duration_seconds": getattr(res, "duration", None),
        }

    async def synthesize(self, text: str, model_id: str, voice: str, fmt: str) -> bytes:
        try:
            res = await get_groq_client().audio.speech.create(
                model=model_id,
                voice=voice,
                input=text,
                response_format=fmt,  # type: ignore[arg-type]
            )
            return await res.read()
        except groq.GroqError as e:
            raise map_groq_error(e) from e
