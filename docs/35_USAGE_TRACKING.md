# 35 — Usage Tracking, Quotas & Cost

## 1. What is tracked

| Dimension | Where |
|---|---|
| Requests (per Groq call, per tool call, per embedding job, STT/TTS) | `usage_records` (one row per upstream call) |
| Tokens (prompt, completion, total) | `usage_records`, aggregated on `messages` and in `usage_daily` |
| Latency (total, TTFT) | `usage_records.latency_ms`, `time_to_first_token_ms`; also metrics |
| Model (`model_key`, `groq_model_id`) | `usage_records` |
| User / API key / conversation / message | FK columns |
| Errors | `status`, `error_code` |
| Estimated cost | `estimated_cost_usd_micros` (from registry pricing) |
| Storage | `SUM(files.size_bytes)` per user (cached counter) |
| Tool usage | `tool_calls` + `usage_records` for web_search/code_execution |

## 2. Recording (`UsageService`)

- `GroqService` returns a `UsageDraft` with every result; callers persist via `UsageService.record(draft, ctx)` in the same transaction as the related domain change when there is one (e.g., message finalization), otherwise in its own short transaction.
- Worker-originated calls (title, summary, memory extraction, embeddings) record with `request_id` = job id.
- Cancelled generations record `status='cancelled'` with the tokens consumed (reported or estimated; `metadata.estimated=true` is kept in logs, not a column).
- Writes are cheap single-row inserts; at the 10,000-user stage `usage_records` becomes monthly range-partitioned (`49_SCALABILITY.md`).

## 3. Cost estimation

```
cost_usd_micros = prompt_tokens * pricing.input_per_million_usd
                + completion_tokens * pricing.output_per_million_usd        # (tokens/1e6 × price) × 1e6
STT: audio_seconds / 3600 × per_hour_usd × 1e6
TTS: characters / 1e6 × per_million_chars_usd × 1e6
```

Computed with `Decimal`, rounded half-up to integer micros. If pricing is `null` → `NULL` (dashboard marks as unknown). Embedding, search (SearXNG), and sandbox costs are infrastructure costs tracked in `51_COST_OPTIMIZATION.md`, not per-request (Brave Search, if used, can be priced via `WEB_SEARCH_COST_PER_QUERY_USD_MICROS`).

Estimated cost is shown only to admins.

## 4. Aggregation

- `aggregate_usage_daily` (ARQ cron every 5 min): upserts `usage_daily` from `usage_records` created since the last watermark (Redis), grouped by `(user_id, day, kind, model_key)`. Idempotent via `INSERT … ON CONFLICT DO UPDATE` using recomputed sums for affected `(user_id, day)` groups.
- Admin dashboards query `usage_daily`; user usage page queries `usage_daily` for charts and Redis counters for live quota meters.

## 5. Plans and limits (`plans.limits`)

`PlanLimits` Pydantic schema (all keys required):

| Key | free | plus | pro |
|---|---|---|---|
| `messages_per_day` | 50 | 500 | 2,000 |
| `monthly_token_quota` | 500,000 | 5,000,000 | 20,000,000 |
| `max_output_tokens` | 2,048 | 4,096 | 8,192 (clamped to model max) |
| `max_message_chars` | 8,000 | 32,000 | 32,000 |
| `max_document_mb` | 10 | 25 | 50 |
| `max_image_mb` | 5 | 10 | 10 |
| `uploads_per_day` | 10 | 100 | 500 |
| `storage_mb` | 100 | 2,048 | 10,240 |
| `max_pages_per_file` | 100 | 500 | 1,000 |
| `max_extracted_tokens_per_file` | 200,000 | 1,000,000 | 2,000,000 |
| `web_search_per_day` | 10 | 100 | 500 |
| `code_executions_per_day` | 10 | 100 | 500 |
| `code_timeout_seconds` | 10 | 10 | 20 |
| `voice_minutes_per_day` | 5 | 60 | 180 |
| `models` | ["primary","fast"] | ["primary","fast","vision"] | ["primary","fast","vision"] |
| `tools` | ["calculator","file_search","web_search","code_execution"] | same | same |
| `memory` | true | true | true |
| `api_access` | false | true | true |

Prices (seed values in migration `0005_seed_plans`; business-owned, editable only via migration/runbook): free ₹0, plus ₹499/month (`price_paise=49900`), pro ₹1,499/month (`149900`). `razorpay_plan_id` is set per environment by the runbook "Create Razorpay plans" (`47_DEPLOYMENT.md` §9) via `UPDATE plans SET razorpay_plan_id=…` executed by an admin script `scripts/set_razorpay_plan_ids.py`.

No separate limit for new accounts: there is no email verification (ADR 0002).

## 6. Quota enforcement architecture

```
request ─► QuotaService.check_and_reserve(principal, kind, amount_estimate)
             Redis counters (fast path)  ── miss/cold ──► rebuild from DB
             ├─ over limit → 429 QUOTA_EXCEEDED (details: quota, limit, used, resets_at)
             └─ OK → reservation token
work ...
completion ─► QuotaService.commit(reservation, actual)   (or .release on early failure)
```

Redis keys (`nova:{env}:q:` prefix):

| Counter | Key | TTL | Increment |
|---|---|---|---|
| Messages today | `msg:{user_id}:{YYYYMMDD}` | 48 h | +1 at submit (reserve); −1 release if the generation fails before producing any output with a provider/internal error |
| Tokens this month | `tok:{user_id}:{YYYYMM}` | 40 d | + actual total tokens at completion (all purposes except `eval`) |
| Web searches today | `ws:{user_id}:{YYYYMMDD}` | 48 h | +1 per executed search |
| Code executions today | `ce:{user_id}:{YYYYMMDD}` | 48 h | +1 per execution |
| Uploads today | `up:{user_id}:{YYYYMMDD}` | 48 h | +1 at initiate |
| Voice seconds today | `vs:{user_id}:{YYYYMMDD}` | 48 h | + audio seconds (STT) + estimated TTS seconds (chars/15) |
| Storage bytes | `nova:{env}:storage:{user_id}` | 5 min (rebuilt from DB on miss) | ± on upload complete/delete |

Rules:
- Periods reset at 00:00 UTC (daily) and the 1st of the month 00:00 UTC (monthly); the UI shows reset times in the user's timezone.
- Token quota check before a turn: `used_tokens + estimated_prompt_tokens + max_output_tokens ≤ monthly_token_quota`, else `QUOTA_EXCEEDED(monthly_token_quota)`. Overshoot of one response is tolerated.
- Counter rebuild on Redis miss: messages today = `COUNT(messages WHERE user_id AND role='user' AND created_at ≥ day_start)`; tokens month = `SUM(usage_daily.prompt_tokens + completion_tokens)` + unaggregated tail from `usage_records`. Rebuild guarded by a short lock to avoid stampedes.
- Nightly `reconcile_quotas` recomputes today's/month's counters for users active in the last 24 h and corrects drift > 1%.
- Plan changes apply immediately (limits read from `plans` via `users.plan_key`, cached 60 s).
- API-key usage counts against the owning user.
- Admin override: `system_settings.quota_overrides` map `{user_id: {limit_key: value}}` for support cases (audited).

## 7. Global budget guard

`system_settings.global_daily_token_budget` (tokens across all users per UTC day, default `null` = disabled). Redis counter `nova:{env}:q:global_tok:{YYYYMMDD}`. Behavior at thresholds in `33_SECURITY.md` §16.

## 8. User-facing usage

- `/settings/usage` (`27_UI_UX_SPECIFICATION.md` §12) using `GET /usage/quota`, `/usage/summary`, `/usage/records`.
- `usage` SSE event includes remaining messages/tokens so the composer hint stays live.
- Emails: when 80% of monthly tokens is reached (once per month) — `send_email(template='quota_warning')`.

## 9. Admin usage

`GET /admin/usage` with grouping by day/model/kind/plan; top users by tokens/cost; error rates by model; cost per user (sum micros / active users) and per request (sum micros / requests). CSV export.

## 10. Testing

- Unit: cost math with Decimal; PlanLimits validation.
- Integration: quota exceeded paths for each counter; release on early failure; rebuild after `FLUSHDB`; reconcile job correctness.
- Load: counters remain accurate (±1%) under 200 concurrent submits for one user (k6).
