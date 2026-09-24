# Load tests (k6)

Run against a **Groq-stub-backed** API (never production with real keys):

```bash
make stub                                   # Groq stub on :8099
cd apps/api && GROQ_BASE_URL=http://localhost:8099 RATE_LIMIT_GLOBAL_IP_PER_MIN=100000 \
  uv run uvicorn app.main:app --port 8010 --host 0.0.0.0
(cd apps/api && uv run python -m tests.fakes.seed_load_users 20) > infra/k6/users.json
make load s=chat_stream                     # SSE streams: completion ≥ 99%, TTFT p95 < 3 s
make load s=api_read                        # mixed reads: p95 < 300 ms
```

Tune with `-e VUS=… -e HOLD=…` (chat) or `-e RPS=… -e DURATION=…` (reads). Seed at least as many
users as VUs: per-user plan limits apply (pro: 40 messages/min). `RATE_LIMIT_GLOBAL_IP_PER_MIN`
must be raised because all load comes from one IP.
