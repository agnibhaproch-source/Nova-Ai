"""Runs eval suites end to end through /api/v1 with a NOVA API key (docs/41 §2, mode `api`).

Each case starts a new conversation (BYOK: the Groq key is supplied per conversation, exactly as
users do), sends the message in non-streaming mode, and scores the final assistant message.

    NOVA_API_URL=http://localhost:3000/api/v1 NOVA_API_KEY=nova_sk_... EVAL_GROQ_API_KEY=gsk_... \\
      uv run python -m nova_evals.runner --suite general_qa --runs 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from nova_evals.report import write_report
from nova_evals.scorers import score

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CaseResult:
    id: str
    suite: str
    run: int
    passed: bool
    checks: list[tuple[str, bool, str]]
    latency_ms: int
    answer: str
    error: str | None = None
    tags: list[str] = field(default_factory=list)


def load_suite(name: str) -> list[dict[str, Any]]:
    path = ROOT / "datasets" / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def client() -> httpx.Client:
    base = os.environ.get("NOVA_API_URL", "http://localhost:3000/api/v1").rstrip("/")
    headers = {"authorization": f"Bearer {os.environ['NOVA_API_KEY']}"}
    if secret := os.environ.get("NOVA_PROXY_SECRET"):  # only when calling FastAPI directly
        headers["x-nova-proxy-secret"] = secret
    return httpx.Client(base_url=base, headers=headers, timeout=180)


def run_case(c: httpx.Client, case: dict[str, Any], run: int, groq_key: str) -> CaseResult:
    started = time.perf_counter()
    try:
        conv = c.post("/conversations", json={"groq_api_key": groq_key})
        conv.raise_for_status()
        cid = conv.json()["data"]["id"]
        body: dict[str, Any] = {"content": case["input"]["message"]}
        if tools := case["input"].get("tools"):
            body["tools"] = tools
        r = c.post(
            f"/conversations/{cid}/messages", json=body, headers={"accept": "application/json"}
        )
        r.raise_for_status()
        msg = r.json()["data"]["assistant_message"]
        parts = msg.get("parts", [])
        answer = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text")
        if msg.get("status") != "completed":
            raise RuntimeError(f"assistant status {msg.get('status')}: {msg.get('error')}")
        checks = score(case.get("expected", {}), answer, parts)
        return CaseResult(
            case["id"],
            case["suite"],
            run,
            all(ok for _, ok, _ in checks),
            checks,
            int((time.perf_counter() - started) * 1000),
            answer[:2000],
            tags=case.get("tags", []),
        )
    except (httpx.HTTPError, RuntimeError, KeyError, ValueError) as e:  # failed case; run continues
        return CaseResult(
            case["id"],
            case["suite"],
            run,
            False,
            [],
            int((time.perf_counter() - started) * 1000),
            "",
            error=f"{type(e).__name__}: {e}"[:500],
            tags=case.get("tags", []),
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", action="append", required=True, help="dataset name (repeatable)")
    ap.add_argument("--runs", type=int, default=1, help="runs per case (variance)")
    ap.add_argument("--limit", type=int, default=0, help="max cases per suite (smoke)")
    ap.add_argument("--baseline", action="store_true", help="compare with baselines/<suite>.json")
    args = ap.parse_args()
    groq_key = os.environ.get("EVAL_GROQ_API_KEY", "")
    if not groq_key:
        print(
            "EVAL_GROQ_API_KEY is required (conversations use a per-chat Groq key)", file=sys.stderr
        )
        return 2
    results: list[CaseResult] = []
    with client() as c:
        for suite in args.suite:
            cases = load_suite(suite)[: args.limit or None]
            for case in cases:
                for run in range(args.runs):
                    res = run_case(c, case, run, groq_key)
                    results.append(res)
                    print(
                        f"{'PASS' if res.passed else 'FAIL'} {res.id} run={run} {res.latency_ms}ms"
                        + (f" — {res.error}" if res.error else "")
                    )
    report = write_report(
        [asdict(r) for r in results],
        ROOT / "reports",
        ROOT / "baselines" if args.baseline else None,
    )
    print(f"\nreport: {report}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
