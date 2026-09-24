"""Deterministic scorers (docs/41 §3). Each returns (passed, detail)."""

from __future__ import annotations

import re
from typing import Any

Result = tuple[bool, str]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def must_include(answer: str, items: list[str]) -> Result:
    missing = [i for i in items if _norm(i) not in _norm(answer)]
    return (not missing, f"missing: {missing}" if missing else "ok")


def must_not_include(answer: str, items: list[str]) -> Result:
    found = [i for i in items if _norm(i) in _norm(answer)]
    return (not found, f"found forbidden: {found}" if found else "ok")


def regex(answer: str, pattern: str) -> Result:
    ok = re.search(pattern, answer, flags=re.IGNORECASE | re.MULTILINE) is not None
    return (ok, "ok" if ok else f"no match for /{pattern}/")


def numeric(answer: str, value: float, tolerance: float = 1e-6) -> Result:
    nums = [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*\.?\d*(?:e-?\d+)?", answer)]
    ok = any(abs(n - value) <= max(tolerance, abs(value) * tolerance) for n in nums)
    return (ok, "ok" if ok else f"expected {value}, saw {nums[:8]}")


def max_words(answer: str, limit: int) -> Result:
    n = len(re.findall(r"\S+", answer))
    return (n <= limit, f"{n} words (limit {limit})")


def bullet_count(answer: str, count: int) -> Result:
    n = len(re.findall(r"^\s*(?:[-*•]|\d+[.)])\s+", answer, flags=re.MULTILINE))
    return (n == count, f"{n} bullets (want {count})")


def script(answer: str, name: str) -> Result:
    """Checks the dominant script, e.g. 'devanagari' for Hindi replies."""
    ranges = {"devanagari": (0x0900, 0x097F), "latin": (0x0041, 0x024F)}
    lo, hi = ranges[name]
    letters = [c for c in answer if c.isalpha()]
    share = sum(lo <= ord(c) <= hi for c in letters) / max(1, len(letters))
    return (share >= 0.5, f"{share:.0%} {name}")


def tool_used(parts: list[dict[str, Any]], name: str) -> Result:
    used = [p.get("tool_name") for p in parts if p.get("type") == "tool_call"]
    return (name in used, f"tools used: {used}")


SCORERS = {
    "must_include": must_include,
    "must_not_include": must_not_include,
    "regex": regex,
    "numeric": numeric,
    "max_words": max_words,
    "bullet_count": bullet_count,
    "script": script,
}


def score(
    expected: dict[str, Any], answer: str, parts: list[dict[str, Any]]
) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    for name, arg in expected.items():
        if name == "tool":
            ok, detail = tool_used(parts, arg)
        elif name == "numeric":
            ok, detail = numeric(answer, **arg) if isinstance(arg, dict) else numeric(answer, arg)
        elif name in SCORERS:
            ok, detail = SCORERS[name](answer, arg)
        else:
            continue  # fields for judge-scored suites (reference_answer, …) are ignored here
        out.append((name, ok, detail))
    return out
