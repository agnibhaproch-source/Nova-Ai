# 34 — Rate Limiting

Rate limits protect availability (short windows, bursts). **Quotas** (daily/monthly allowances tied to plans) are in `35_USAGE_TRACKING.md`. Both are enforced server-side in FastAPI using Redis.

## 1. Algorithm

**GCRA (Generic Cell Rate Algorithm)** implemented as a Redis Lua script (`app/ratelimit/lua/gcra.lua`), executed atomically via `EVALSHA`:

```lua
-- KEYS[1] = key ; ARGV = now_ms, emission_interval_ms (period/limit), burst (limit), cost
local tat = tonumber(redis.call("GET", KEYS[1]) or ARGV[1])
local now = tonumber(ARGV[1]); local T = tonumber(ARGV[2]); local burst = tonumber(ARGV[3]); local cost = tonumber(ARGV[4])
tat = math.max(tat, now)
local new_tat = tat + T * cost
local allow_at = new_tat - burst * T
if allow_at > now then
  return {0, math.ceil((allow_at - now)/1000), math.max(0, math.floor((now - (tat - burst*T)) / T)), math.ceil((tat - now)/1000)}
end
redis.call("SET", KEYS[1], new_tat, "PX", math.ceil(new_tat - now) + 1000)
return {1, 0, math.floor((now - (new_tat - burst*T)) / T), math.ceil((new_tat - now)/1000)}
-- returns {allowed, retry_after_s, remaining, reset_s}
```

Time source: Redis `TIME` is not used inside the script for determinism in tests; the app passes `now_ms` from its clock (NTP-synced hosts).

## 2. Keys

`nova:{env}:rl:{policy}:{dimension}:{identifier}` — examples:
- `nova:prod:rl:global_ip:ip:203.0.113.4`
- `nova:prod:rl:chat_messages:user:<uuid>`
- `nova:prod:rl:chat_messages:apikey:<uuid>`
- `nova:prod:rl:auth_login_email:email:<sha256(email)>` (hashed to avoid storing emails in Redis)

## 3. Dimensions

| Dimension | Identifier | Source |
|---|---|---|
| IP | client IP from `X-Forwarded-For` (first hop set by our proxy; trusted only when the proxy secret is valid) | middleware |
| User | `principal.user_id` | dependency |
| API key | `principal.api_key_id` (in addition to user limits) | dependency |
| Endpoint | policy name per route | dependency |
| Plan | limits scale by `principal.plan_key` | policy table |

IPv6 addresses are bucketed by /64.

## 4. Policies

Defaults (configurable in `app/ratelimit/policies.py`; overridable by admins via `system_settings.rate_limit_overrides`):

Per-user policies are the same for every plan and sit above Groq's own per-key limits, so the user's Groq API key is the real ceiling; they exist only as abuse guards (ADR 0004).

| Policy | Dimension | free | plus | pro | Notes |
|---|---|---|---|---|---|
| `global_ip` | IP | 300/min | same | same | All `/api/v1` requests; middleware |
| `auth_login_ip` | IP | 20 / 15 min | — | — | |
| `auth_login_email` | email hash | 10 / 15 min | — | — | + lockout (09 §5) |
| `auth_signup` | IP | 5 / hour | — | — | |
| `auth_password_forgot` | IP / email hash | 10/h / 3/h | — | — | |
| `auth_verify_resend` | user | 3 / hour | — | — | |
| `api_key_auth_fail` | IP | 30 / min | — | — | on invalid keys |
| `api_read` | user | 600/min | same | same | GET endpoints default |
| `api_write` | user | 300/min | same | same | unsafe methods default |
| `chat_messages` | user (+ api key) | 60/min, burst 20 | same | same | message create/regenerate/edit |
| `stream_resume` | user | 120/min | same | same | |
| `file_upload` | user | 60/min | same | same | initiate |
| `rag_search` | user | 120/min | same | same | |
| `tool_web_search` | user | 40/min | same | same | inside ToolEngine |
| `tool_code_execution` | user | 20/min | same | same | inside ToolEngine |
| `voice_transcribe` | user | 40/min | same | same | |
| `voice_speech` | user | 60/min | same | same | |
| `exports` | user | 1 / 24 h | — | — | returns `EXPORT_RATE_LIMITED` |
| `analytics_ingest` | IP | 60/min | — | — | |
| `admin` | user | 300/min | — | — | admin endpoints |
| `web_search_global` | global | `WEB_SEARCH_GLOBAL_RPS` | — | — | provider protection |

API-key requests apply the plan's user policy **and** a per-key policy at 50% of the plan's rate, so one leaked key cannot consume the whole user budget.

## 5. Enforcement points

- `IpRateLimitMiddleware` — `global_ip` for all requests (cheap; before auth).
- Route dependency `rate_limit("policy")` — resolves principal dimension and plan, runs GCRA; multiple policies can be stacked.
- `ToolEngine` — tool policies.
- Auth service — login email policy (needs the parsed body).

Order within a request: IP limit → auth → endpoint/user limit → quota check (35) → work.

## 6. HTTP 429 response behavior

```
HTTP/1.1 429 Too Many Requests
Retry-After: 20
RateLimit-Limit: 6
RateLimit-Remaining: 0
RateLimit-Reset: 20
RateLimit-Policy: 6;w=60
Content-Type: application/json
{"error":{"code":"RATE_LIMITED","message":"You're sending messages too quickly. Try again in 20 seconds.","details":[{"policy":"chat_messages","scope":"user"}],"request_id":"…","retryable":true,"retry_after_seconds":20}}
```

- Successful responses on rate-limited endpoints include `RateLimit-Limit/Remaining/Reset` headers (IETF draft semantics) for the most restrictive applied policy.
- For SSE endpoints, limits are checked before the stream starts; the 429 is JSON.
- Frontend shows countdown and re-enables send automatically when it expires.

## 7. Failure behavior (Redis unavailable)

| Policy class | Behavior |
|---|---|
| Auth policies (`auth_*`, `api_key_auth_fail`) | **Fail closed**: `503 SERVICE_DEGRADED` |
| All others | **Fail open** with an in-process fallback limiter (per-instance token buckets using `cachetools.TTLCache`, limits divided by expected instance count `RATE_LIMIT_FALLBACK_DIVISOR`, default 4) |

Metric `nova_ratelimit_fallback_total` and alert on use.

## 8. Observability and abuse

- Metrics: `nova_ratelimit_decisions_total{policy,result}`.
- Log `ratelimit.blocked` (INFO) with policy, dimension type, user_id (no IP in logs beyond the request log).
- User exceeding 100 blocks/hour → automated `moderation_flags(category='rate_abuse')` (at most one open flag per user per day).

## 9. Testing

Unit tests for GCRA script via real Redis (burst, steady rate, retry_after math, cost > 1); integration tests for headers and 429 envelope; fallback behavior with Redis stopped; k6 test verifying limits hold under concurrency (no over-admission > 5%).
