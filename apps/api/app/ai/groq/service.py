"""GroqService: single gateway to Groq with retries, fallback, circuit breaking, metrics
and usage extraction (docs/14 §4–§12). No other module talks to Groq."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from app.ai.groq import ratelimits
from app.ai.groq.errors import ModelUnavailableError, ProviderError
from app.ai.groq.provider import GroqProvider
from app.ai.models_registry import ModelConfig, get_registry
from app.ai.provider import (
    CallContext,
    ChatChunk,
    ChatRequest,
    ChatResult,
    LLMMessage,
    ResolvedChatRequest,
    Usage,
)
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode

log = structlog.get_logger("app.groq")
M = TypeVar("M", bound=BaseModel)
IDLE_TIMEOUT_S = 30.0


class GenerationCancelled(Exception):
    pass


@dataclass
class _Circuit:
    failures: list[float]
    calls: list[float]
    open_until: float = 0.0


class GroqService:
    def __init__(self, provider: GroqProvider | None = None) -> None:
        self.provider = provider or GroqProvider()
        self._sem = asyncio.Semaphore(get_settings().GROQ_MAX_CONCURRENCY_PER_PROCESS)
        self._circuits: dict[str, _Circuit] = {}

    # ------------------------------------------------------------------ helpers
    def _resolve(self, req: ChatRequest, model: ModelConfig) -> ResolvedChatRequest:
        max_out = req.max_output_tokens or model.default_max_output_tokens
        if model.max_output_tokens:
            max_out = min(max_out, model.max_output_tokens)
        return ResolvedChatRequest(
            request=req,
            groq_model_id=model.groq_model_id,
            temperature=req.temperature
            if req.temperature is not None
            else model.default_temperature,
            top_p=req.top_p if req.top_p is not None else model.default_top_p,
            max_output_tokens=max_out,
            supports_tools=bool(model.supports_tools),
            supports_json_mode=bool(model.supports_json_mode),
            supports_parallel_tool_calls=model.supports_parallel_tool_calls,
        )

    def _circuit(self, model_id: str) -> _Circuit:
        return self._circuits.setdefault(model_id, _Circuit([], []))

    def _circuit_open(self, model_id: str) -> bool:
        return self._circuit(model_id).open_until > time.monotonic()

    def _record(self, model_id: str, ok: bool, code: ErrorCode | None = None) -> None:
        # Per-key problems (bad key, that key's rate limit) say nothing about Groq's health.
        if code in (ErrorCode.GROQ_KEY_INVALID, ErrorCode.PROVIDER_RATE_LIMITED):
            return
        c, now = self._circuit(model_id), time.monotonic()
        c.calls = [t for t in c.calls if t > now - 60] + [now]
        c.failures = [t for t in c.failures if t > now - 60] + ([] if ok else [now])
        if len(c.calls) >= 20 and len(c.failures) / len(c.calls) >= 0.5:
            c.open_until = now + 30
            log.error("groq.circuit_open", groq_model_id=model_id)

    @staticmethod
    def _backoff(attempt: int, retry_after: int | None) -> float:
        if retry_after:
            return float(min(retry_after, 10))
        return random.uniform(0, min(8.0, 0.5 * 2**attempt))

    def _pick_model(self, model: ModelConfig) -> ModelConfig:
        if self._circuit_open(model.groq_model_id):
            if model.fallback_key:
                return get_registry().resolve(model.fallback_key)
            raise ProviderError(ErrorCode.PROVIDER_UNAVAILABLE, retryable=False)
        return model

    # ------------------------------------------------------------------ public API
    async def stream_chat(
        self, req: ChatRequest, *, ctx: CallContext, on_model: list[ModelConfig] | None = None
    ) -> AsyncIterator[ChatChunk]:
        """Yields chunks. Retries/fallback only before the first emitted token.
        `on_model` (if given) receives the ModelConfig actually used."""
        model = self._pick_model(get_registry().resolve(req.model_key))
        attempt = 0
        settings = get_settings()
        while True:
            emitted = False
            started = time.perf_counter()
            if on_model is not None:
                on_model[:] = [model]
            try:
                async with self._sem:
                    stream = await self.provider.open_stream(self._resolve(req, model))
                    try:
                        it = stream.__aiter__()
                        while True:
                            if ctx.cancel_event is not None and ctx.cancel_event.is_set():
                                raise GenerationCancelled
                            try:
                                chunk = await asyncio.wait_for(it.__anext__(), IDLE_TIMEOUT_S)
                            except StopAsyncIteration:
                                break
                            except TimeoutError as e:
                                raise ProviderError(
                                    ErrorCode.PROVIDER_TIMEOUT, retryable=True
                                ) from e
                            if chunk.text_delta or chunk.tool_call_deltas:
                                emitted = True
                            yield chunk
                    finally:
                        await stream.aclose()
                self._record(model.groq_model_id, True)
                await ratelimits.record(
                    ctx.user_id, model.groq_model_id, getattr(stream, "rate_limits", None)
                )
                log.info(
                    "groq.request.completed",
                    purpose=req.purpose,
                    model_key=model.key,
                    attempt=attempt,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                return
            except ModelUnavailableError:
                self._record(model.groq_model_id, False)
                if emitted or not model.fallback_key:
                    raise
                log.warning("groq.fallback", from_key=model.key, to_key=model.fallback_key)
                model = get_registry().resolve(model.fallback_key)
            except ProviderError as e:
                self._record(model.groq_model_id, False, e.code)
                log.warning(
                    "groq.request.failed",
                    purpose=req.purpose,
                    model_key=model.key,
                    code=str(e.code),
                    attempt=attempt,
                    emitted=emitted,
                )
                if (
                    emitted
                    or not e.retryable_before_first_token
                    or attempt >= settings.GROQ_MAX_RETRIES
                ):
                    raise
                attempt += 1
                await asyncio.sleep(self._backoff(attempt, e.retry_after))

    async def complete(self, req: ChatRequest, *, ctx: CallContext) -> ChatResult:
        model = self._pick_model(get_registry().resolve(req.model_key))
        attempt = 0
        while True:
            try:
                async with self._sem:
                    result = await self.provider.complete(self._resolve(req, model))
                self._record(model.groq_model_id, True)
                await ratelimits.record(ctx.user_id, model.groq_model_id, result.rate_limits)
                return result
            except ModelUnavailableError:
                self._record(model.groq_model_id, False)
                if not model.fallback_key:
                    raise
                model = get_registry().resolve(model.fallback_key)
            except ProviderError as e:
                self._record(model.groq_model_id, False, e.code)
                if not e.retryable_before_first_token or attempt >= get_settings().GROQ_MAX_RETRIES:
                    raise
                attempt += 1
                await asyncio.sleep(self._backoff(attempt, e.retry_after))

    async def complete_json(self, req: ChatRequest, schema: type[M], *, ctx: CallContext) -> M:
        model = get_registry().resolve(req.model_key)
        messages = list(req.messages)
        if not model.supports_json_mode:
            messages.append(
                LLMMessage(role="system", content="Respond with a single JSON object only.")
            )
        attempt_req = ChatRequest(
            **{**req.__dict__, "messages": messages, "json_mode": bool(model.supports_json_mode)}
        )
        for attempt in range(2):
            result = await self.complete(attempt_req, ctx=ctx)
            try:
                return schema.model_validate_json(_extract_json(result.text))
            except (ValidationError, ValueError) as e:
                if attempt == 1:
                    raise ProviderError(ErrorCode.PROVIDER_ERROR, retryable=False) from e
                messages = [
                    *messages,
                    LLMMessage(role="assistant", content=result.text),
                    LLMMessage(
                        role="user",
                        content=f"Invalid JSON: {str(e)[:300]}. "
                        "Return only the corrected JSON object.",
                    ),
                ]
                attempt_req = ChatRequest(**{**attempt_req.__dict__, "messages": messages})
        raise AssertionError("unreachable")

    async def transcribe(
        self, audio: bytes, filename: str, *, model_id: str, language: str | None, ctx: CallContext
    ) -> dict[str, object]:
        async with self._sem:
            return await self.provider.transcribe(audio, filename, model_id, language)

    async def synthesize(
        self, text: str, *, model_id: str, voice: str, fmt: str, ctx: CallContext
    ) -> bytes:
        async with self._sem:
            return await self.provider.synthesize(text, model_id, voice, fmt)

    async def verify_models(self) -> dict[str, str]:
        """Checks configured model ids exist at Groq; adopts reported context windows."""
        reg = get_registry()
        report: dict[str, str] = {}
        try:
            available = await self.provider.list_models()
        except ProviderError as e:
            log.warning("groq.models.verify_failed", code=str(e.code))
            return {m.key: "unknown" for m in reg.all() if m.enabled}
        reg.adopt_context_windows({k: v for k, v in available.items() if v})
        for m in reg.all():
            if m.enabled:
                report[m.key] = "ok" if m.groq_model_id in available else "missing"
        return report


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    candidate = text[start : end + 1]
    json.loads(candidate)
    return candidate


def estimate_cost_micros(model: ModelConfig, usage: Usage) -> int | None:
    p = model.pricing
    if p.input_per_million_usd is None or p.output_per_million_usd is None:
        return None
    micros = (
        Decimal(usage.prompt_tokens) * p.input_per_million_usd
        + Decimal(usage.completion_tokens) * p.output_per_million_usd
    )
    return int(micros.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


_service: GroqService | None = None


def get_groq_service() -> GroqService:
    global _service
    if _service is None:
        _service = GroqService()
    return _service


def reset_groq_service() -> None:
    global _service
    _service = None


__all__ = ["AppError", "GenerationCancelled", "GroqService", "get_groq_service"]
