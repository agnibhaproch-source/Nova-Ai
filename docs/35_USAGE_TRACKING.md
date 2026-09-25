# 35 — Usage Tracking & Cost

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
- Admin dashboards query `usage_daily`; the user Usage page reads totals from `usage_records` and the Groq key's limits from Redis (§6).

## 5. Plans and limits (`plans.limits`)

Nova has no paid plans and no usage quotas (ADR 0004). The `free`, `plus` and `pro` rows still exist, but migration `0016_no_usage_quotas` gives them identical capability settings:

| Key | Value |
|---|---|
| `max_output_tokens` | 65,536 (replies are bounded by each model's own output limit in `config/models.yaml`) |
| `max_message_chars` | 100,000 |
| `max_document_mb` | 50 |
| `max_image_mb` | 10 |
| `storage_mb` | 10,240 |
| `max_pages_per_file` | 1,000 |
| `max_extracted_tokens_per_file` | 2,000,000 |
| `code_timeout_seconds` | 20 |
| `models` | ["primary","fast","vision"] |
| `tools` | ["calculator","file_search","web_search","code_execution"] |
| `memory` | true |
| `api_access` | true |

The former count-based keys (`messages_per_day`, `monthly_token_quota`, `uploads_per_day`, `web_search_per_day`, `code_executions_per_day`, `voice_minutes_per_day`) were removed.

No separate limit for new accounts: there is no email verification (ADR 0002).

## 6. No quota enforcement: the Groq key is the ceiling

Nova does not count or cap messages, tokens, tool calls, voice or uploads. The only limits are:

- **The Groq API key's own rate limits.** Groq enforces them per key and returns them on every chat completion in response headers: `x-ratelimit-limit-requests` / `-remaining-requests` / `-reset-requests` (requests per day) and `x-ratelimit-limit-tokens` / `-remaining-tokens` / `-reset-tokens` (tokens per minute); resets are durations such as `2m59.56s`. `GroqProvider` reads them via the SDK's `with_raw_response`, and `GroqService` stores the latest snapshot per (user, model) in the Redis hash `nova:{env}:groqrl:{user_id}` (field = `groq_model_id`, value = JSON of numbers only; 7-day TTL) through `app/ai/groq/ratelimits.py`. When the key is exhausted Groq answers 429, surfaced as `PROVIDER_RATE_LIMITED` (docs/32).
- **Per-minute abuse guards** (docs/34 §4), the same for every plan and set above Groq's per-key limits.
- **Size limits** from §5 (message length, file size, storage).

`QuotaService` keeps `plan_limits` (capability settings above) and `usage_totals` (messages today, tokens today, tokens this month from `messages` and `usage_records`, informational only).

## 7. Global budget guard

`system_settings.global_daily_token_budget` (tokens across all users per UTC day, default `null` = disabled). Redis counter `nova:{env}:q:global_tok:{YYYYMMDD}`. Behavior at thresholds in `33_SECURITY.md` §16.

## 8. User-facing usage

- `/settings/usage` (`27_UI_UX_SPECIFICATION.md` §12) using `GET /usage/current`: the Groq key's limits per model (requests left today, tokens left this minute, reset times, when Groq last reported them) and the user's totals. Groq's daily token limit is not in the headers, so the page links to Groq's console for it.
- The `usage` SSE event carries token counts only; the web client refetches `/usage/current` on it.

## 9. Admin usage

`GET /admin/usage` with grouping by day/model/kind/plan; top users by tokens/cost; error rates by model; cost per user (sum micros / active users) and per request (sum micros / requests). CSV export.

## 10. Testing

- Unit: cost math with Decimal; parsing of Groq's rate-limit headers and reset durations.
- Integration: no Nova-side cap blocks a message; `/usage/current` reports the Groq limits from the (stubbed) response headers and the user's totals.
