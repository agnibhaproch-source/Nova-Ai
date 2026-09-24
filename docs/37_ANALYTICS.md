# 37 — Product Analytics

## 1. Approach

First-party analytics stored in PostgreSQL `analytics_events` (no third-party analytics SDK in v1). Rationale: privacy, no content leakage, simple compliance. A future export to a warehouse is possible via the read replica.

**Never** include conversation content, message text, file names, file content, memory content, search queries, custom instructions, emails, or full IP addresses in analytics.

## 2. Collection paths

| Source | Mechanism |
|---|---|
| Server (authoritative) | `AnalyticsService.track(name, user_id, properties)` called in `after_commit` hooks; batched insert (in-process buffer flushed every 2 s or 100 events; worker path writes directly) |
| Web client (UX events) | `lib/analytics.ts` batches events (max 20, flush every 5 s or on `visibilitychange` hidden via `navigator.sendBeacon`) to `POST /api/v1/analytics/events` |

Opt-out: if `analytics_opt_out` is true, the client does not send and the server drops user-attributed events (server-side authoritative events are dropped too, except billing events needed for business reporting, which are stored **without** `user_id`).

Anonymous visitors: `nova_aid` first-party cookie (random UUID, 1 year, `SameSite=Lax`, not HttpOnly) used only for landing → signup funnel; linked to `user_id` at signup by a `signup` event property `anonymous_id`.

Do-Not-Track / Global Privacy Control header present → client sends no events for anonymous visitors.

## 3. Event catalogue (allow-list)

Event names and allowed properties are defined in `app/services/analytics_events.py` (`EVENTS: dict[str, type[BaseModel]]`); unknown events/properties are dropped.

| Event | Source | Properties |
|---|---|---|
| `page_viewed` | web | `path_template` (e.g. `/c/[id]`, never real ids), `referrer_domain` |
| `signup` | server | `method: "email"`, `anonymous_id?` |
| `login` | server | `method: "password"` |
| `onboarding_completed` | server | `use_cases: [str]` (chip ids), `memory_enabled`, `skipped` |
| `chat_created` | server | `model_key`, `source: "web"|"api"` |
| `message_sent` | server | `model_key`, `has_attachments`, `attachment_kinds`, `is_edit`, `is_regenerate`, `web_search_enabled`, `code_execution_enabled`, `source`, `char_count_bucket` ("<100","100-500","500-2k",">2k") |
| `message_completed` | server | `model_key`, `status`, `finish_reason`, `ttft_ms`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `tool_count`, `citation_count`, `used_rag`, `used_memory` |
| `generation_stopped` | server | `model_key`, `tokens_before_stop` |
| `feedback_given` | server | `rating`, `reasons` |
| `file_uploaded` | server | `kind`, `extension`, `size_bucket`, `purpose` |
| `file_processed` | server | `extension`, `status`, `duration_ms`, `page_count_bucket`, `error_code?` |
| `tool_used` | server | `tool_name`, `status`, `latency_ms` |
| `memory_updated` | server | `op: create|update|delete`, `source` |
| `search_performed` | web | `result_count_bucket` |
| `voice_used` | server | `mode: dictation|voice_mode|read_aloud`, `duration_bucket` |
| `upgrade_clicked` | web | `from_plan`, `location` (e.g. `composer_quota`, `billing_page`) |
| `subscription_started` | server | `plan_key`, `amount_paise` |
| `subscription_cancelled` | server | `plan_key`, `tenure_days` |
| `subscription_payment_failed` | server | `plan_key` |
| `api_key_created` | server | `scopes_count` |
| `export_requested` | server | — |
| `account_deleted` | server | `tenure_days` (no user_id stored) |

Common properties auto-added: `source`, `app_version`, `plan_key` (server), `device_type` (web: mobile/tablet/desktop from viewport), `locale`.

## 4. Storage & retention

`analytics_events` table (`08_DATABASE_SCHEMA.md` §22); retention 400 days (`purge_old_analytics`). Partitioned monthly at the 10,000-user stage.

## 5. Privacy review checklist for new events

1. No free text from users.
2. No identifiers other than `user_id`/`anonymous_id`.
3. Numeric values bucketed where they could fingerprint.
4. Documented in this file's catalogue.
5. Added to the allow-list schema with tests.

## 6. Admin analytics (`GET /admin/analytics`)

| Metric | Definition |
|---|---|
| `funnel` | landing `page_viewed` (anon) → `signup` → first `message_sent` → `message_sent` on day 2+ ; conversion % per step |
| `retention` | Weekly cohorts by signup week; % with ≥ 1 `message_sent` in week N |
| `feature_usage` | Share of active users using RAG, web search, code execution, voice, memory; tool success rates |
| `quality` | 👍/👎 ratio by model; regenerate rate; stop rate; failure rate |
| `revenue` | New subscriptions, cancellations, MRR trend (from `subscriptions`/`payments`) |

Queries run against `analytics_events` + domain tables with date bounds; results cached 10 min in Redis.

## 7. Testing

Unit tests: allow-list filtering drops unknown properties; opt-out suppression; no content-bearing fields can be passed (Pydantic `extra="forbid"`). Integration: events emitted on key flows (signup, message completed, upload).
