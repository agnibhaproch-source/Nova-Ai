# Redis unhealthy / rate-limit fallback

Redis holds sessions cache, rate limits, SSE replay streams, job queue and BYOK chat keys.
It is **not** a system of record: losing it logs nobody out permanently (sessions are in Postgres),
but in-flight streams can't resume and users must re-enter chat Groq keys.

**Check:** `redis-cli ping`, `INFO memory` (`used_memory` vs `maxmemory`), `evicted_keys` (must stay 0,
policy is `noeviction`), Admin → Health → `redis`.

**Fix**
- Memory high → check big keys (`redis-cli --bigkeys`); SSE streams are trimmed with TTLs — if they aren't, restart the API to re-apply; scale the instance.
- Unreachable → the API falls back to in-process rate limiting (`RATE_LIMIT_FALLBACK_DIVISOR`) and keeps serving; restore Redis, then restart the worker.

**Verify:** `ping` OK, evictions 0, "rate-limit fallback active" alert clears.
