"""TEST-ONLY Groq emulator (docs/40 §3). Implements the subset of Groq's OpenAI-compatible API
used by NOVA (chat completions stream/non-stream, models list) as an httpx MockTransport.
Never imported by production code (enforced by review + ruff banned imports)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class Scenario:
    keys_seen: list[str] = field(default_factory=list)
    reply: str = "Hello from the stub."
    chunk_size: int = 4
    delay_s: float = 0.0
    fail_statuses: list[int] = field(default_factory=list)  # consumed one per request
    usage_on_final: bool = True
    json_reply: str | None = None
    requests: list[dict[str, Any]] = field(default_factory=list)
    stream_closed: bool = False


scenario = Scenario()


# Shape of Groq's per-key rate-limit headers (requests per day, tokens per minute).
RATE_LIMIT_HEADERS = {
    "x-ratelimit-limit-requests": "1000",
    "x-ratelimit-remaining-requests": "999",
    "x-ratelimit-reset-requests": "1m26.4s",
    "x-ratelimit-limit-tokens": "8000",
    "x-ratelimit-remaining-tokens": "7500",
    "x-ratelimit-reset-tokens": "3.75s",
}


def reset() -> Scenario:
    global scenario
    scenario = Scenario()
    return scenario


def _usage(body: dict[str, Any], text: str) -> dict[str, int]:
    prompt = sum(len(str(m.get("content", ""))) for m in body.get("messages", [])) // 4 + 1
    completion = max(1, len(text) // 4)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


async def _stream(body: dict[str, Any], sc: Scenario) -> AsyncIterator[bytes]:
    text = sc.reply
    base = {
        "id": "chatcmpl-stub",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": body["model"],
    }
    try:
        first = {
            **base,
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}
            ],
        }
        yield f"data: {json.dumps(first)}\n\n".encode()
        for i in range(0, len(text), sc.chunk_size):
            if sc.delay_s:
                await asyncio.sleep(sc.delay_s)
            piece = text[i : i + sc.chunk_size]
            chunk = {
                **base,
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n".encode()
        final: dict[str, Any] = {
            **base,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        if sc.usage_on_final:
            final["x_groq"] = {"id": "req_stub", "usage": _usage(body, text)}
        yield f"data: {json.dumps(final)}\n\n".encode()
        yield b"data: [DONE]\n\n"
    finally:
        sc.stream_closed = True


async def handler(request: httpx.Request) -> httpx.Response:
    sc = scenario
    auth = request.headers.get("authorization", "")
    sc.keys_seen.append(auth.removeprefix("Bearer "))
    if "gsk_revoked" in auth:  # lets tests exercise rejected user keys (BYOK)
        return httpx.Response(401, json={"error": {"message": "Invalid API Key"}})
    if request.url.path == "/openai/v1/models":
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {
                        "id": "test-model-primary",
                        "object": "model",
                        "created": 0,
                        "owned_by": "stub",
                        "context_window": 8192,
                    },
                    {
                        "id": "test-model-fast",
                        "object": "model",
                        "created": 0,
                        "owned_by": "stub",
                        "context_window": 8192,
                    },
                ],
            },
        )
    if request.url.path != "/openai/v1/chat/completions":
        return httpx.Response(404, json={"error": {"message": "not found"}})
    body = json.loads(request.content)
    sc.requests.append(body)
    if not request.headers.get("authorization", "").startswith("Bearer "):
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})
    if sc.fail_statuses:
        status = sc.fail_statuses.pop(0)
        return httpx.Response(
            status,
            headers={"retry-after": "0"},
            json={"error": {"message": f"stub failure {status}"}},
        )
    if body.get("stream"):
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", **RATE_LIMIT_HEADERS},
            content=_stream(body, sc),
        )
    text = sc.json_reply if body.get("response_format") and sc.json_reply else sc.reply
    return httpx.Response(
        200,
        headers=RATE_LIMIT_HEADERS,
        json={
            "id": "chatcmpl-stub",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": _usage(body, text),
        },
    )


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))
