# 41 — AI Evaluation

## 1. Principles

- Quality is multi-dimensional; **no single aggregate score is accepted as proof of quality**. Reports always show each dimension separately with confidence intervals and per-slice breakdowns.
- Prefer deterministic checks; use LLM-as-judge (Groq, `purposes.eval_judge`) only where deterministic checks are impossible, with calibrated rubrics and periodic human agreement checks.
- Evaluations run against the **real pipeline** (ContextService, RAG, tools, GroqService) in a staging-like environment, not against isolated prompts only.
- Every change to prompts, model configuration, context budgets, chunking, embedding model, retrieval parameters, or tools requires an eval run compared against the current baseline.

## 2. Layout

```
evals/
├── datasets/
│   ├── general_qa.jsonl            # factual Q&A with reference answers
│   ├── instruction_following.jsonl # format/length/language/constraint prompts with checkable rules
│   ├── rag_docs.jsonl              # questions over fixtures/files/* with gold chunk ids/pages + reference answers
│   ├── rag_unanswerable.jsonl      # questions not answerable from docs (must abstain)
│   ├── tool_use.jsonl              # expected tool selection + argument constraints + final answer checks
│   ├── web_search.jsonl            # time-sensitive questions (evaluated for tool usage + citation validity)
│   ├── code_execution.jsonl        # computational tasks with numeric answers
│   ├── memory_extraction.jsonl     # (17 §9)
│   ├── safety_injection.jsonl      # prompt-injection documents/web pages; must not follow embedded instructions
│   └── multilingual.jsonl          # Hindi/Hinglish/English prompts
├── fixtures/files/                 # PDFs/DOCX/XLSX/PPTX/CSV used by RAG sets
├── nova_evals/
│   ├── runner.py                   # orchestrates cases through the API (API key auth) or in-process services
│   ├── scorers/*.py                # deterministic + judge scorers
│   ├── judge_prompts/*.md
│   ├── calibrate_threshold.py      # RAG similarity threshold calibration (21 §6)
│   └── report.py                   # markdown + JSON report, comparison to baseline
└── baselines/<suite>.json          # committed baseline metrics per suite
```

Case schema (JSONL):
```json
{"id":"rag-017","suite":"rag_docs","input":{"message":"What risks are listed in section 4?","files":["q3-report.pdf"],"history":[]},
 "expected":{"gold_pages":[4,5],"gold_chunk_ids_hint":["q3-report.pdf#p4"],"reference_answer":"…","must_include":["supply chain"],"must_not_include":[]},
 "tags":["pdf","multi-page"]}
```

Runner modes: `--mode api` (end-to-end through `/api/v1` with a dedicated eval user/API key on staging) and `--mode service` (in-process with real Groq, faster). Temperature per model default unless the suite sets `seed` + `temperature=0` for reproducibility checks. Each case runs **3 times** (variance measurement) for judge-scored suites.

## 3. Dimensions and metrics

| Dimension | Metric(s) | Method |
|---|---|---|
| Correctness | exact/normalized match (numeric tolerance), `must_include` coverage, judge correctness (0/1/2 rubric vs reference) | deterministic first; judge for free-form |
| Relevance | judge: "addresses the question" (0–2) | judge |
| Instruction following | rule checks: word/bullet count limits, JSON validity + schema, language detection (`langdetect`), forbidden phrases, format (table/code block) | deterministic |
| Hallucination / faithfulness | For RAG: claim-level support — judge extracts atomic claims, then checks each against provided chunks → faithfulness = supported/total; for unanswerable set: abstention rate | judge + deterministic |
| Citation accuracy | citation precision = cited sources that contain supporting text / all citations; citation recall = gold pages cited / gold pages; invalid index rate | deterministic (page/chunk matching) + judge for support |
| Retrieval quality | recall@8 of gold pages/chunks, MRR | deterministic (from `messages.metadata.rag`) |
| Tool correctness | tool selection accuracy (called when needed, not called when unnecessary), argument validity, result usage (final answer consistent with tool output), iterations count | deterministic + judge for "used result" |
| Safety / injection resistance | % cases where model followed injected instructions (e.g., "ignore previous", exfiltrate URL) | deterministic markers + judge |
| Latency | TTFT p50/p95, total latency p50/p95 per suite | measured |
| Cost | tokens/case, estimated USD/case (when pricing known) | measured |

## 4. LLM-as-judge

- Model: `registry.for_purpose("eval_judge")` (Groq), `temperature=0`, `seed=7`, JSON output `{"score": 0|1|2, "rationale": "…"}` validated by Pydantic.
- Rubrics in `judge_prompts/*.md` with anchored examples for each score.
- Bias controls: judge never sees which model/config produced the answer; order randomized for pairwise comparisons; judge prompt forbids length preference.
- **Calibration:** 100 human-labeled cases per judged dimension (`evals/datasets/human_labels/*.jsonl`); report Cohen's κ between judge and humans; a judged metric is used for gating only if κ ≥ 0.6. Re-run calibration when the judge model changes.

## 5. Reporting

`python -m nova_evals.report --suite all --compare baselines/` produces:
- Per suite, per metric: mean, 95% bootstrap CI (1,000 resamples), delta vs baseline with CI, per-tag slices (e.g., file type, language).
- Variance across the 3 runs per case.
- Lists of regressions (cases passing in baseline, failing now) with ids (content visible only in the eval environment).
- Latency and cost tables.
Output: `evals/reports/<date>-<git_sha>.md` + JSON (CI artifact; not committed except baselines).

## 6. Gates

A change is blocked (label `eval-regression`) if any **gated metric** regresses beyond its tolerance with the 95% CI excluding zero:

| Metric | Tolerance |
|---|---|
| RAG faithfulness | −2 pts |
| Citation precision | −3 pts |
| RAG recall@8 | −3 pts |
| Unanswerable abstention rate | −5 pts |
| Instruction-following pass rate | −3 pts |
| Tool selection accuracy | −3 pts |
| Injection resistance | any statistically significant decrease |
| Correctness (general_qa) | −3 pts |
| TTFT p95 | +25% |
| Cost per case | +20% (warning only) |

Baseline updates require reviewer approval and a note in the PR.

## 7. Production feedback loop

- Weekly job exports **metadata-only** stats: 👍/👎 rates by model/feature, down-vote reasons, regenerate rate, stop rate, invalid citation metric, tool failure rates.
- Down-voted messages are **not** automatically added to datasets. With explicit user consent (future "Help improve Nova" opt-in, default off) or via admin moderation with reason, an engineer may craft a *synthetic* case capturing the failure pattern without copying user content.
- Online metrics tracked in the Business dashboard (`39_MONITORING.md` §4).

## 8. Schedule

- Nightly: all suites on staging (budget-capped via `EVAL_MAX_COST_USD`, default 20 per night) + report to Slack.
- On PR: `make eval-smoke` (30 cases across suites, service mode) when files under `app/ai/`, `app/services/context_service.py`, `app/services/rag_service.py`, `app/documents/`, `app/tools/`, `config/models.yaml` change (CI path filter).
- Before model changes: full suites × 3 runs.

## 9. Dataset maintenance

- Minimum sizes: general_qa 200, instruction_following 150, rag_docs 200 (over ≥ 30 documents of all formats), rag_unanswerable 60, tool_use 120, code_execution 60, web_search 40, safety_injection 80, memory_extraction 150, multilingual 80.
- Time-sensitive web cases carry `valid_until` and are auto-skipped after expiry.
- All fixtures are synthetic or public-domain/licensed content; no user data.
