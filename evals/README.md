# Nova evals (docs/41)

Runs suites end to end through `/api/v1` with a NOVA API key, the same way users call Nova.
Each case opens a new chat with a Groq key (BYOK) and scores the final answer with deterministic
scorers (`must_include`, `must_not_include`, `regex`, `numeric`, `max_words`, `bullet_count`,
`script`, `tool`).

```bash
cd evals && uv sync
uv run pytest -q tests_scorers.py                           # scorer unit tests
NOVA_API_URL=http://localhost:3000/api/v1 \
NOVA_API_KEY=nova_sk_...  EVAL_GROQ_API_KEY=gsk_... \
uv run python -m nova_evals.runner --suite general_qa --suite instruction_following --baseline
```

Reports land in `reports/` (git-ignored). Baselines in `baselines/<suite>.json` (`{"pass_rate": 90.0}`)
are committed after a reviewed run; a drop of ≥ 5 points fails the gate.

Not yet included: RAG suites (need fixture documents + an embedding model), LLM-as-judge scoring,
web search and code-execution suites (need those services enabled).
