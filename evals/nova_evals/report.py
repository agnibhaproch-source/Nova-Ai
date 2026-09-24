"""Markdown + JSON report with per-suite pass rates and baseline comparison (docs/41 §5–§6)."""

from __future__ import annotations

import json
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

REGRESSION_POINTS = 5.0  # pass-rate drop (percentage points) that fails the gate


def summarize(results: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        by[r["suite"]].append(r)
    return {
        suite: {
            "cases": len(rs),
            "pass_rate": round(100 * sum(r["passed"] for r in rs) / len(rs), 1),
            "errors": sum(1 for r in rs if r["error"]),
            "p50_latency_ms": statistics.median(r["latency_ms"] for r in rs),
        }
        for suite, rs in by.items()
    }


def write_report(results: list[dict[str, Any]], out_dir: Path, baselines: Path | None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    summary = summarize(results)
    lines = [
        "# Nova eval report",
        "",
        f"Generated {stamp}",
        "",
        "| Suite | Cases | Pass rate | Errors | p50 latency | Baseline | Δ |",
        "|---|---|---|---|---|---|---|",
    ]
    regressions: list[str] = []
    for suite, s in summary.items():
        base = None
        if baselines and (baselines / f"{suite}.json").exists():
            base = json.loads((baselines / f"{suite}.json").read_text())["pass_rate"]
        delta = s["pass_rate"] - base if base is not None else None
        if delta is not None and delta <= -REGRESSION_POINTS:
            regressions.append(suite)
        lines.append(
            f"| {suite} | {s['cases']} | {s['pass_rate']}% | {s['errors']} | {s['p50_latency_ms']:.0f} ms | "
            f"{f'{base}%' if base is not None else '—'} | {f'{delta:+.1f}' if delta is not None else '—'} |"
        )
    failed = [r for r in results if not r["passed"]]
    if failed:
        lines += ["", "## Failures", ""]
        for r in failed[:50]:
            why = r["error"] or "; ".join(f"{n}: {d}" for n, ok, d in r["checks"] if not ok)
            lines.append(f"- `{r['id']}` (run {r['run']}): {why}")
    if regressions:
        lines += [
            "",
            f"**Regression gate failed:** {', '.join(regressions)} dropped ≥ {REGRESSION_POINTS} points.",
        ]
    md = out_dir / f"report-{stamp}.md"
    md.write_text("\n".join(lines) + "\n")
    (out_dir / f"report-{stamp}.json").write_text(
        json.dumps({"summary": summary, "results": results}, indent=2, default=str)
    )
    return md
