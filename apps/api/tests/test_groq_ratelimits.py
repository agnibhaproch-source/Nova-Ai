"""Parsing the Groq key's rate-limit headers (docs/35 §6, ADR 0004)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.ai.groq.ratelimits import from_headers, parse_duration


@pytest.mark.parametrize(
    ("raw", "seconds"),
    [
        ("7.66s", 7.66),
        ("2m59.56s", 179.56),
        ("1h2m3s", 3723.0),
        ("120ms", 0.12),
        ("", None),
        ("soon", None),
    ],
)
def test_parse_duration(raw: str, seconds: float | None) -> None:
    got = parse_duration(raw)
    assert got == pytest.approx(seconds) if seconds is not None else got is None


def test_from_headers() -> None:
    snap = from_headers(
        {
            "X-RateLimit-Limit-Requests": "1000",
            "X-RateLimit-Remaining-Requests": "12",
            "X-RateLimit-Reset-Requests": "2m0s",
            "X-RateLimit-Limit-Tokens": "8000",
            "X-RateLimit-Remaining-Tokens": "not-a-number",
        }
    )
    assert snap is not None
    assert snap["requests_limit"] == 1000 and snap["requests_remaining"] == 12
    assert snap["tokens_limit"] == 8000 and snap["tokens_remaining"] is None
    assert snap["tokens_reset_at"] is None
    reset = datetime.fromisoformat(snap["requests_reset_at"])
    observed = datetime.fromisoformat(snap["observed_at"])
    assert (reset - observed).total_seconds() == pytest.approx(120, abs=1)


def test_no_rate_limit_headers() -> None:
    assert from_headers({"content-type": "application/json"}) is None
