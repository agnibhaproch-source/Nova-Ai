"""Redis GCRA rate limiter with policies and an in-memory fallback (docs/34_RATE_LIMITING.md)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import structlog
from cachetools import TTLCache
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.redis import get_redis, rkey

log = structlog.get_logger()
_LUA = (Path(__file__).parent / "lua" / "gcra.lua").read_text()


@dataclass(frozen=True)
class Rate:
    limit: int
    period_s: int
    burst: int | None = None

    @property
    def emission_ms(self) -> float:
        return self.period_s * 1000 / self.limit


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int
    remaining: int
    reset: int
    limit: int
    period_s: int


# policy -> plan -> Rate   ("*" = all plans)
POLICIES: dict[str, dict[str, Rate]] = {
    "global_ip": {"*": Rate(300, 60)},
    "auth_login_ip": {"*": Rate(20, 900)},
    "auth_login_email": {"*": Rate(10, 900)},
    "auth_signup": {"*": Rate(5, 3600)},
    "auth_password_forgot_ip": {"*": Rate(10, 3600)},
    "auth_password_forgot_email": {"*": Rate(3, 3600)},
    "api_key_auth_fail": {"*": Rate(30, 60)},
    # Per-minute abuse guards only, the same for every plan and set above Groq's own per-key
    # limits so the Groq key is the real ceiling (ADR 0004).
    "api_read": {"*": Rate(600, 60)},
    "api_write": {"*": Rate(300, 60)},
    "chat_messages": {"*": Rate(60, 60, burst=20)},
    "stream_resume": {"*": Rate(120, 60)},
    "analytics_ingest": {"*": Rate(60, 60)},
    "file_upload": {"*": Rate(60, 60)},
    "rag_search": {"*": Rate(120, 60)},
    "tool_web_search": {"*": Rate(40, 60)},
    "tool_code_execution": {"*": Rate(20, 60)},
    "voice_transcribe": {"*": Rate(40, 60)},
    "voice_speech": {"*": Rate(60, 60)},
    "exports": {"*": Rate(1, 86400)},
    "admin": {"*": Rate(300, 60)},
}
FAIL_CLOSED = {
    "auth_login_ip",
    "auth_login_email",
    "auth_signup",
    "auth_password_forgot_ip",
    "auth_password_forgot_email",
    "api_key_auth_fail",
}

_fallback: TTLCache[str, float] = TTLCache(maxsize=100_000, ttl=3600)


def rate_for(policy: str, plan: str = "free") -> Rate:
    if policy == "global_ip":
        # Configurable so a perf environment can load-test from few IPs (docs/40 §10).
        return Rate(get_settings().RATE_LIMIT_GLOBAL_IP_PER_MIN, 60)
    table = POLICIES[policy]
    return table.get(plan) or table["*"]


def _fallback_check(key: str, rate: Rate, now_ms: float) -> Decision:
    divisor = max(1, get_settings().RATE_LIMIT_FALLBACK_DIVISOR)
    limit = max(1, rate.limit // divisor)
    t = rate.period_s * 1000 / limit
    burst = limit
    tat = max(_fallback.get(key, now_ms), now_ms)
    new_tat = tat + t
    if new_tat - burst * t > now_ms:
        return Decision(
            False, int((new_tat - burst * t - now_ms) / 1000) + 1, 0, 0, limit, rate.period_s
        )
    _fallback[key] = new_tat
    return Decision(True, 0, int((now_ms - (new_tat - burst * t)) / t), 0, limit, rate.period_s)


async def check(policy: str, identifier: str, *, plan: str = "free", cost: int = 1) -> Decision:
    rate = rate_for(policy, plan)
    burst = rate.burst or rate.limit
    key = rkey("rl", policy, identifier)
    now_ms = time.time() * 1000
    try:
        res = await get_redis().eval(  # type: ignore[misc]
            _LUA, 1, key, str(int(now_ms)), str(rate.emission_ms), str(burst), str(cost)
        )
        allowed, retry_after, remaining, reset = (int(x) for x in res)
        return Decision(bool(allowed), retry_after, remaining, reset, rate.limit, rate.period_s)
    except RedisError:
        if policy in FAIL_CLOSED:
            raise AppError(ErrorCode.SERVICE_DEGRADED) from None
        log.warning("ratelimit.fallback", policy=policy)
        return _fallback_check(key, rate, now_ms)


async def enforce(policy: str, identifier: str, *, plan: str = "free") -> Decision:
    decision = await check(policy, identifier, plan=plan)
    if not decision.allowed:
        log.info("ratelimit.blocked", policy=policy)
        raise AppError(
            ErrorCode.RATE_LIMITED,
            f"You're doing that too often. Try again in {decision.retry_after} seconds.",
            details=[{"policy": policy}],
            retry_after=max(1, decision.retry_after),
        )
    return decision
