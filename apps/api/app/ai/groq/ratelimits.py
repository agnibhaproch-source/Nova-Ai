"""The Groq API key's own rate limits, read from Groq's response headers (docs/35 §6, ADR 0004).

Groq returns on every chat completion (requests are per day, tokens per minute):
  x-ratelimit-limit-requests, x-ratelimit-remaining-requests, x-ratelimit-reset-requests
  x-ratelimit-limit-tokens,   x-ratelimit-remaining-tokens,   x-ratelimit-reset-tokens
Resets are durations such as "2m59.56s" or "7.66s". The latest snapshot per (user, model) is
kept in Redis so the Usage page can show how much of the key's allowance is left. No secret is
stored: the snapshot holds only numbers.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from redis.exceptions import RedisError

from app.core.redis import get_redis, rkey

log = structlog.get_logger()
TTL_S = 7 * 86400
_DURATION = re.compile(
    r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?"
)


def _int(v: str | None) -> int | None:
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def parse_duration(v: str | None) -> float | None:
    """'2m59.56s' → 179.56. Returns None for anything unrecognised."""
    if not v:
        return None
    m = _DURATION.fullmatch(v.strip())
    if not m or not any(m.groups()):
        return None
    h, mi, s, ms = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


def from_headers(headers: Mapping[str, str]) -> dict[str, Any] | None:
    """Rate-limit snapshot from a Groq response, or None when Groq sent no such headers."""
    h = {k.lower(): v for k, v in headers.items()}
    if "x-ratelimit-limit-requests" not in h and "x-ratelimit-limit-tokens" not in h:
        return None
    now = datetime.now(UTC)

    def reset_at(name: str) -> str | None:
        secs = parse_duration(h.get(name))
        return (now + timedelta(seconds=secs)).isoformat() if secs is not None else None

    return {
        "requests_limit": _int(h.get("x-ratelimit-limit-requests")),
        "requests_remaining": _int(h.get("x-ratelimit-remaining-requests")),
        "requests_reset_at": reset_at("x-ratelimit-reset-requests"),
        "tokens_limit": _int(h.get("x-ratelimit-limit-tokens")),
        "tokens_remaining": _int(h.get("x-ratelimit-remaining-tokens")),
        "tokens_reset_at": reset_at("x-ratelimit-reset-tokens"),
        "observed_at": now.isoformat(),
    }


def _key(user_id: uuid.UUID) -> str:
    return rkey("groqrl", str(user_id))


async def record(
    user_id: uuid.UUID | None, groq_model_id: str, snap: dict[str, Any] | None
) -> None:
    if user_id is None or snap is None:
        return
    try:
        await get_redis().hset(_key(user_id), groq_model_id, json.dumps(snap))  # type: ignore[misc]
        await get_redis().expire(_key(user_id), TTL_S)
    except RedisError:
        log.warning("groq.ratelimits.redis_unavailable")


async def latest(user_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """{groq_model_id: snapshot} for the models this user has called recently."""
    try:
        raw = await get_redis().hgetall(_key(user_id))  # type: ignore[misc]
    except RedisError:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        try:
            out[k.decode() if isinstance(k, bytes) else k] = json.loads(v)
        except ValueError:
            continue
    return out
