# 36 — Admin Panel

## 1. Access model

- Routes under `/admin` (Next.js `(admin)` group) render only for `role ∈ {support, admin}` (server-side check in layout → `notFound()` otherwise).
- **All authorization is enforced in FastAPI** (`require_role`) on `/api/v1/admin/*`; the UI check is cosmetic.
- Session auth only (API keys rejected). Admin sessions: idle timeout 12 h (instead of 7 days) — enforced when `principal.role != 'user'`.
- Every admin mutation writes `audit_logs` (actor, action, target, reason, request_id, ip) in the same transaction.
- Admins cannot change their own role or status (`CANNOT_MODIFY_SELF`). At least one active admin must remain (demotion of the last admin → `409 CONFLICT`).
- Production UI shows a red "PRODUCTION" badge; staging shows amber.

## 2. Navigation & pages

| Page | Role | Data source |
|---|---|---|
| Dashboard | support | `GET /admin/dashboard` |
| Users / User detail | support (read), admin (mutate) | `/admin/users*` |
| Usage | support | `/admin/usage` |
| Conversations (metadata) | support; content view admin + reason | `/admin/conversations*` |
| System health | support | `/admin/health` |
| Errors | support | `/admin/errors` |
| Audit logs | support | `/admin/audit-logs` |
| Moderation | support | `/admin/moderation/flags*` |
| Models | support (view), admin (toggle) | `/admin/models*` |
| Plans | support (view), admin (edit limits) | `/admin/plans*` |
| Analytics | support | `/admin/analytics` |
| Settings | admin | `/admin/settings*` |

## 3. Dashboard

Time range selector (24 h / 7 d / 30 d). Auto-refresh every 60 s.

KPI cards (value + delta vs previous period + sparkline):
1. Active users (DAU for 24 h; WAU/MAU otherwise)
2. New signups
3. Messages sent
4. Tokens (prompt + completion)
5. Estimated Groq cost (USD) — "unknown" badge if pricing missing
6. Error rate (% of assistant messages `failed`)
7. p95 TTFT (from `messages.time_to_first_token_ms`)

Charts: messages per hour/day (bar), tokens by model (stacked area), error rate by code (line), signups (line). Tables: top 10 users by tokens (id, email masked `p***@example.com` for support role, plan, tokens, cost), recent failures (message ids, error codes).

## 4. Users

- Table columns: email, display name, role, status, plan, created, last login, messages (30 d), tokens (30 d).
- Filters: search (email/name/id), status, role, plan; sort by created/last login/tokens.
- Row click → detail page: profile summary, usage chart (30 d), sessions (count, last seen; revoke all), API keys (count, prefixes; revoke all), moderation flags, recent audit events for this user (as target or actor), files count/storage.
- Actions (admin): Suspend/Unsuspend (reason required; suspending revokes sessions and API keys, cancels active generations), Change role (user/support/admin), Plan override (sets `users.plan_key`; plans no longer differ, ADR 0004), Revoke sessions, Quota override (per-limit values).
- Support role sees emails masked except domain unless they open the detail page (detail view is audited `admin.user.viewed`).

## 5. Usage

Filters: date range, group by (day/model/kind/plan), user id. Charts + table; totals row; CSV export. Cost per user and per request metrics (`35_USAGE_TRACKING.md` §9).

## 6. Conversations (metadata) and content access

- List (support): conversation id, user id, created, last activity, message count, model, flags count. Titles hidden by default (titles can contain personal content); admin can reveal a title with a reason (audited).
- Content view (admin only): "View content" button opens a dialog requiring a reason (10–500 chars, e.g., support ticket id) → `GET /admin/conversations/{id}/messages?reason=…` → read-only transcript with a persistent banner "Access audited". Each access creates `audit_logs(action='admin.content.accessed', reason=…)`. Content access is used only for moderation reports and user-requested support.

## 7. System health

Cards with status (ok/degraded/down) and details:
- Database: latency of `SELECT 1`, pool usage, replication lag (if replica), migration revision.
- Redis: latency, memory usage, connected clients.
- Object storage: HEAD on a canary object latency.
- Groq: model verification report (per configured model: present/active), circuit breaker states, last 15 min error rate & p95 latency, near-limit indicators from rate-limit headers.
- Embeddings service: health + latency.
- Web search provider: health (cached probe every 5 min).
- Sandbox runner(s): health, concurrent executions, capacity.
- Workers: last heartbeat per worker (`nova:{env}:worker:heartbeat:{id}` TTL 60 s), queue depths per queue (`files`, `files_low`, `default`, `email`), oldest job age, failed jobs (24 h).
- API instances: count of active SSE streams per instance (from Redis `nova:{env}:instances` hash updated every 15 s).

## 8. Errors

Aggregated counts by error code and source for the range (from `usage_records.status='error'`, `messages.error_code`, `tool_calls.error_code`, `files.error_code`). Drill-down lists recent items (ids, timestamps, user id, request_id) with a link to Sentry search by `request_id` (Sentry URL built from the `sentry_org_url` system setting, §11) — no content.

## 9. Subscriptions & payments

Removed with billing (ADR 0004).

## 10. Audit logs

Filterable by actor, action prefix (e.g., `admin.`), target, date range; immutable; CSV export (audited). Shows reason and metadata JSON (pretty printed).

## 11. Configuration (system settings)

Typed registry in `app/services/settings_service.py`; each key has a Pydantic type, default, and description. Cached in Redis 30 s; updates invalidate cache.

| Key | Type | Default | Effect |
|---|---|---|---|
| `signups_enabled` | bool | true | Blocks signup when false |
| `block_disposable_emails` | bool | true | Signup email domain check |
| `chat_enabled` | bool | true | Emergency kill switch: new messages return `SERVICE_DEGRADED` |
| `maintenance_banner` | str \| null | null | Banner shown in app (≤ 200 chars) |
| `disabled_model_keys` | list[str] | [] | Hides/disables models |
| `disabled_tools` | list[str] | [] | Disables tools globally |
| `web_search_blocked_domains` | list[str] | [] | Excluded from results |
| `global_daily_token_budget` | int \| null | null | Global cost guard |
| `rate_limit_overrides` | dict | {} | Per-policy overrides |
| `quota_overrides` | dict | {} | Per-user limit overrides |
| `memory_extraction_enabled` | bool | true | Global switch for extraction |
| `sentry_org_url` | str \| null | null | For error deep links |

`GET /api/v1/app-config` (public, cached 30 s) exposes only `maintenance_banner`, `signups_enabled`, and `chat_enabled` for the UI.

## 12. Moderation

- Queue of `moderation_flags` (filters: status, category, source). Detail shows subject user summary, related conversation/message ids, reporter note, automated rule id.
- Actions: set status (reviewing/resolved/dismissed) with resolution note; "Suspend user" shortcut (admin); "View content" (admin, reason = flag id auto-filled).
- Automated sources: malware upload, rate abuse, sandbox abuse, payment failures, user reports.

## 13. Models & plans

- Models: table from registry (key, display name, `groq_model_id`, enabled, admin-disabled, capabilities, context window, pricing, verification status, deprecation date); toggle enabled (admin, reason).
- Plans: view limits; edit limits JSON through a form with validation (admin, reason). Prices are not shown (no billing, ADR 0004).

## 14. Implementation notes

- Admin backend services live in `app/services/admin_service.py` + `app/repositories/admin/*` (unscoped queries allowed only here; code review requires `require_role` on every admin route; a test asserts all `/admin` routes have a role dependency).
- Admin tables use offset pagination with capped totals (`30_API_SPECIFICATION.md` §6).
- Heavy aggregate queries use `usage_daily` and, from Phase 11, the read replica (`DATABASE_READ_REPLICA_URL`).
