# 31 — API Endpoints

All routes are prefixed with `/api/v1` unless noted. Conventions in `30_API_SPECIFICATION.md`; error codes in `32_ERROR_HANDLING.md`.

**Legend — Auth column**

| Code | Meaning |
|---|---|
| `P` | Public (no auth) |
| `S` | Session cookie required |
| `S+C` | Session + CSRF (unsafe methods) |
| `K:scope` | Also accepts API key with that scope |
| `R:support` / `R:admin` | Role required (admin satisfies support) |
| `SO` | Session only (API keys rejected) |

Common errors not repeated per endpoint: `401 AUTH_REQUIRED`, `401 AUTH_INVALID`, `403 CSRF_FAILED`, `403 INSUFFICIENT_SCOPE`, `422 VALIDATION_ERROR`, `429 RATE_LIMITED`, `500 INTERNAL_ERROR`, `503 SERVICE_DEGRADED`. "Owned" means ownership check → `404 RESOURCE_NOT_FOUND` otherwise.

---

## 1. Health (no prefix)

| Method & route | Auth | Response | Notes |
|---|---|---|---|
| `GET /healthz` | P | `200 {"status":"ok"}` | Liveness; no dependencies checked; exempt from proxy secret |
| `GET /readyz` | P (proxy secret or internal network) | `200 {"status":"ready","checks":{"database":"ok","redis":"ok","migrations":"ok","storage":"ok","groq":"ok|degraded"}}` / `503` if database, redis, or migrations fail | Groq/storage degradations do not fail readiness |

## 2. Auth

| Method & route | Auth | Request | Response | Errors | Side effects |
|---|---|---|---|---|---|
| `POST /auth/signup` | P (Origin check) | `{email, password, display_name, accept_terms}` | `201 {data:{user}}` + cookies | `409 EMAIL_ALREADY_REGISTERED`, `403 SIGNUPS_DISABLED`, `422 PASSWORD_POLICY` | user, prefs, session, email token; email job; audit; analytics `signup` |
| `POST /auth/login` | P (Origin) | `{email, password}` | `200 {data:{user}}` + cookies | `401 INVALID_CREDENTIALS`, `423 ACCOUNT_LOCKED`, `403 ACCOUNT_SUSPENDED` | session; audit; analytics `login` |
| `POST /auth/logout` | S+C | — | `204` (clears cookies) | — | session revoked; audit |
| `GET /auth/session` | S | — | `200 {data:{user, session}}` | `401` | may re-issue `nova_csrf` |
| `POST /auth/password/forgot` | P (Origin) | `{email}` | `202` always | — | reset token + email if user exists; audit |
| `POST /auth/password/reset` | P (Origin) | `{token, new_password}` | `204` | `400 TOKEN_INVALID`, `422 PASSWORD_POLICY` | password updated, all sessions revoked, audit |

`user` object: `{id, email, display_name, avatar_url, role, plan_key, onboarding_completed, created_at}`.

## 3. Users / account (all `SO`)

| Method & route | Auth | Request | Response | Errors | Side effects |
|---|---|---|---|---|---|
| `GET /users/me` | S | — | `{data:user}` | — | — |
| `PATCH /users/me` | S+C | `{display_name?}` | `{data:user}` | — | — |
| `PUT /users/me/avatar` | S+C | `{file_id}` (owned, image, ready) | `{data:user}` | `404`, `422 INVALID_FILE` | avatar derivative job; old avatar deleted |
| `DELETE /users/me/avatar` | S+C | — | `204` | — | object deleted |
| `GET /users/me/preferences` | S | — | `{data:preferences}` | — | — |
| `PATCH /users/me/preferences` | S+C | any subset of preference fields | `{data:preferences}` | `422 MODEL_NOT_AVAILABLE` | cache invalidation |
| `POST /users/me/password` | S+C | `{current_password, new_password}` | `204` | `401 INVALID_CREDENTIALS`, `422 PASSWORD_POLICY` | other sessions revoked; audit |
| `POST /users/me/onboarding/complete` | S+C | `{custom_instructions?, memory_enabled?}` | `{data:user}` | — | analytics `onboarding_completed` |
| `GET /users/me/sessions` | S | — | `{data:[session]}` | — | — |
| `DELETE /users/me/sessions/{session_id}` | S+C | — | `204` | `404` | revoke; audit |
| `POST /users/me/sessions/revoke-others` | S+C | — | `{data:{revoked_count}}` | — | revoke; audit |
| `POST /users/me/exports` | S+C | `{include_files?: bool}` | `202 {data:export}` | `429 EXPORT_RATE_LIMITED` | export job; audit |
| `GET /users/me/exports` | S | — | `{data:[export]}` (last 5) | — | — |
| `GET /users/me/exports/{export_id}/download` | S | — | `302` presigned (5 min) | `404`, `409 EXPORT_NOT_READY`, `410 EXPORT_EXPIRED` | audit |
| `DELETE /users/me` | S+C | `{password, confirmation:"DELETE"}` | `204` (clears cookies) | `401 INVALID_CREDENTIALS`, `422 CONFIRMATION_REQUIRED`, `502 PAYMENT_PROVIDER_ERROR` | cancel subscription; status deleted; sessions/API keys revoked; purge job; audit |

## 4. Models, capabilities, tools, app config

| Method & route | Auth | Response |
|---|---|---|
| `GET /app-config` | P | `{data:{maintenance_banner, signups_enabled, chat_enabled}}` (`Cache-Control: public, max-age=30`) — `36_ADMIN_PANEL.md` §11 |
| `GET /models` | S / K:chat:write | `{data:[{key, display_name, description, capabilities:{tools, vision, json}, context_window, is_default, locked: bool, required_plan: str|null}]}` — includes plan-locked models with `locked:true` |
| `GET /capabilities` | S / K:chat:write | See `25_MULTIMODAL.md` §1 |
| `GET /tools` | S / K:chat:write | `{data:[{name, display_name, description, enabled, disabled_reason: "plan"|"preference"|"admin"|"model"|null, daily_limit, used_today}]}` |

## 5. Conversations

| Method & route | Auth | Request | Response | Errors | Side effects |
|---|---|---|---|---|---|
| `GET /conversations` | S / K:conversations:read | query `limit, cursor, archived=false, deleted=false` | list of `conversation_summary` | `400 INVALID_CURSOR` | — |
| `POST /conversations` | S+C / K:chat:write | `{model_key?}` | `201 {data:conversation}` | `422 MODEL_NOT_AVAILABLE` | — (analytics `chat_created` fires on first message) |
| `GET /conversations/search` | S / K:conversations:read | `q (1..200), limit, cursor` | `{data:[{conversation_id, title, message_id, snippet, highlights:[[start,end]], last_message_at}], page}` | — | — |
| `GET /conversations/{id}` | S / K:conversations:read | — | `{data:conversation}` (owned) | `404` | — |
| `PATCH /conversations/{id}` | S+C / K:conversations:write | `{title?, pinned?, archived?, model_key?}` | `{data:conversation}` | `404`, `409 LIMIT_REACHED` (pins) | — |
| `DELETE /conversations/{id}` | S+C / K:conversations:write | query `permanent=false` | `204` | `404`, `409 NOT_IN_TRASH` (permanent on non-trashed) | soft/hard delete; active generation cancelled |
| `POST /conversations/{id}/restore` | S+C / K:conversations:write | — | `{data:conversation}` | `404`, `410 RESTORE_WINDOW_EXPIRED` | — |
| `POST /conversations/bulk-delete` | S+C | `{all?: true, conversation_ids?: [uuid ≤100]}` | `{data:{deleted_count}}` | — | soft delete |
| `POST /conversations/{id}/branch` | S+C / K:conversations:write | `{message_id}` | messages list (current path) | `404` | `current_leaf_message_id` updated |
| `GET /conversations/{id}/files` | S / K:files:read | — | `{data:[file]}` | `404` | — |
| `POST /conversations/{id}/files` | S+C / K:files:write | `{file_id}` | `201 {data:file}` | `404`, `409 LIMIT_REACHED` (≤ 50 files per conversation) | link row |
| `DELETE /conversations/{id}/files/{file_id}` | S+C / K:files:write | — | `204` | `404` | unlink |

`conversation`: `{id, title, title_source, model_key, pinned, archived, deleted_at, purge_at, current_leaf_message_id, last_message_at, created_at, message_count, attached_file_count}`.

## 6. Messages

| Method & route | Auth | Request | Response | Errors | Side effects |
|---|---|---|---|---|---|
| `GET /conversations/{id}/messages` | S / K:conversations:read | `limit (≤100, default 50), before` | `12_MESSAGE_SYSTEM.md` §9 | `404` | — |
| `POST /conversations/{id}/messages` | S+C / K:chat:write | headers `Accept`, `Idempotency-Key`; body `{content, parent_message_id?, file_ids?, model_key?, tools?:{web_search?, code_execution?}}` | SSE (`13_STREAMING.md`) or `200 {data:{user_message, assistant_message}}` | `404`, `409 GENERATION_IN_PROGRESS`, `409 CONVERSATION_DELETED`, `409 IDEMPOTENCY_KEY_REUSED`, `422 MODEL_NOT_AVAILABLE`, `422 MODEL_CAPABILITY_MISSING`, `422 CONTEXT_TOO_LARGE`, `409 FILE_NOT_READY`, `429 QUOTA_EXCEEDED` | rows, generation, usage, title/memory/summary jobs, analytics `message_sent`/`message_completed` |
| `GET /messages/{id}` | S / K:conversations:read | — | `{data:message}` | `404` | — |
| `POST /messages/{id}/regenerate` | S+C / K:chat:write | `{model_key?}` | SSE / JSON | as above + `409 INVALID_MESSAGE_STATE` | new sibling |
| `POST /messages/{id}/edit` | S+C / K:chat:write | `{content, file_ids?}` | SSE / JSON | as above | new branch |
| `POST /messages/{id}/cancel` | S+C / K:chat:write | — | `202 {data:{status}}` or `200` if terminal | `404` | cancel flag |
| `GET /messages/{id}/stream` | S / K:chat:write | header `Last-Event-ID` or `?last_event_id=` | SSE | `404` | — |
| `PUT /messages/{id}/feedback` | S+C | `{rating, reasons?, comment?}` | `{data:feedback}` | `404`, `409 INVALID_MESSAGE_STATE` | analytics `feedback_given` (rating only) |
| `DELETE /messages/{id}/feedback` | S+C | — | `204` | `404` | — |
| `POST /messages/{id}/report` | S+C | `{category, details?}` | `201 {data:{id}}` | `404` | moderation flag |
| `GET /messages/{id}/memories` | S | — | `{data:[memory]}` (memories used for that message that still exist) | `404` | — |

## 7. Files

| Method & route | Auth | Request | Response | Errors | Side effects |
|---|---|---|---|---|---|
| `POST /files` | S+C / K:files:write | `{filename, size_bytes, mime_type, purpose, conversation_id?}` | `201 {data:{file, upload:{url, fields, expires_at}}}` | `415 UNSUPPORTED_FILE_TYPE`, `415 FILE_TYPE_MISMATCH`, `413 FILE_TOO_LARGE`, `413 STORAGE_QUOTA_EXCEEDED`, `429 QUOTA_EXCEEDED` | file row |
| `POST /files/{id}/complete` | S+C / K:files:write | — | `{data:file}` | `404`, `422 UPLOAD_INVALID` | processing job; analytics `file_uploaded` |
| `GET /files` | S / K:files:read | `kind, status, q, limit, cursor` | list of `file` | — | — |
| `GET /files/{id}` | S / K:files:read | — | `{data:file}` | `404` | — |
| `GET /files/{id}/download` | S / K:files:read | — | `302` presigned | `404`, `409 FILE_NOT_READY` | — |
| `GET /files/{id}/content-url` | S / K:files:read | `variant=display|original` (images) | `{data:{url, expires_at}}` | `404`, `422 INVALID_FILE` | — |
| `POST /files/{id}/retry` | S+C / K:files:write | — | `202 {data:file}` | `404`, `409 INVALID_FILE_STATE`, `429 RATE_LIMITED` | job |
| `DELETE /files/{id}` | S+C / K:files:write | — | `204` | `404` | chunks deleted; purge job |

`file`: `{id, filename, extension, mime_type, size_bytes, kind, purpose, status, stage, progress, error_code, error_message, page_count, chunk_count, created_at, processed_at}`.

## 8. RAG

| Method & route | Auth | Request | Response |
|---|---|---|---|
| `POST /rag/search` | S+C / K:files:read | `{query, file_ids?, conversation_id?, top_k?}` | `20_RAG_SYSTEM.md` §10 |

## 9. Memories

| Method & route | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /memories` | S / K:memories:read | `q, category, limit, cursor` | list of `memory {id, content, category, importance, source, created_at, updated_at, last_used_at}` | — |
| `POST /memories` | S+C | `{content, category?, importance?}` | `201 {data:memory}` | `422 MEMORY_CONTENT_REJECTED`, `409 LIMIT_REACHED` |
| `PATCH /memories/{id}` | S+C | `{content?, category?, importance?}` | `{data:memory}` | `404`, `422 MEMORY_CONTENT_REJECTED` |
| `DELETE /memories/{id}` | S+C | — | `204` | `404` |
| `POST /memories/{id}/restore` | S+C | — | `{data:memory}` | `404`, `410 RESTORE_WINDOW_EXPIRED` |
| `DELETE /memories` | S+C | query `confirm=true` | `{data:{deleted_count}}` | `422 CONFIRMATION_REQUIRED` |
| `GET /memories/notifications` | S | — | `{data:[{type:"memory_updated", memory_ids, created_at}]}` (pops) | — |

## 10. Voice

| Method & route | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `POST /voice/transcriptions` | S+C / K:chat:write | multipart `audio`, `language?` | `{data:{text, language, duration_seconds}}` | `503 VOICE_UNAVAILABLE`, `413 AUDIO_TOO_LONG`, `415 UNSUPPORTED_FILE_TYPE`, `422 NO_SPEECH_DETECTED`, `429 QUOTA_EXCEEDED`, provider errors |
| `POST /voice/speech` | S+C | `{message_id, voice?, format?:"mp3"}` | `200 audio/mpeg` stream | `503 VOICE_UNAVAILABLE`, `404`, `409 INVALID_MESSAGE_STATE`, `429 QUOTA_EXCEEDED` |

## 11. Usage

| Method & route | Auth | Response |
|---|---|---|
| `GET /usage/quota` | S / K:usage:read | `{data:{plan_key, period_resets:{daily_at, monthly_at}, limits:{…}, used:{messages_today, tokens_month, web_searches_today, code_executions_today, uploads_today, storage_bytes, voice_seconds_today}}}` |
| `GET /usage/summary` | S / K:usage:read | query `from, to` (≤ 90 days) → `{data:{days:[{day, requests, prompt_tokens, completion_tokens, errors}], totals:{…}, by_model:[…]}}` |
| `GET /usage/records` | S / K:usage:read | `limit, cursor, kind?` → list of `{id, created_at, kind, model_key, conversation_id, conversation_title, prompt_tokens, completion_tokens, latency_ms, status}` |

(Estimated costs are not shown to end users; admins only.)

## 12. Billing (all `SO`)

| Method & route | Auth | Request | Response | Errors | Side effects |
|---|---|---|---|---|---|
| `GET /billing/plans` | P | — | `{data:[{key, name, description, price_paise, currency, limits_summary, is_current?}]}` | — | — |
| `GET /billing/subscription` | S | — | `{data:subscription|null}` | — | — |
| `POST /billing/subscriptions` | S+C | `{plan_key}` + `Idempotency-Key` | `201 {data:{subscription_id, razorpay_subscription_id, razorpay_key_id, plan, prefill:{name,email}}}` | `409 SUBSCRIPTION_EXISTS`, `422 PLAN_NOT_PURCHASABLE`, `502 PAYMENT_PROVIDER_ERROR` | Razorpay `subscription.create` (`plan_id`, `total_count=120`, `customer_notify=1`, `notes={user_id, subscription_id}`); `subscriptions` row `created`; audit |
| `POST /billing/subscriptions/verify` | S+C | `{razorpay_payment_id, razorpay_subscription_id, razorpay_signature}` | `{data:subscription}` | `400 PAYMENT_SIGNATURE_INVALID`, `404` | verify `HMAC_SHA256(key_secret, payment_id + "|" + subscription_id)` (constant-time); fetch subscription from Razorpay to confirm status; set `authenticated/active`; `users.plan_key` updated when `active`; audit; analytics `subscription_started` |
| `POST /billing/subscription/cancel` | S+C | `{at_period_end: true}` | `{data:subscription}` | `404 NO_ACTIVE_SUBSCRIPTION`, `502 PAYMENT_PROVIDER_ERROR` | Razorpay cancel (`cancel_at_cycle_end=1`); `cancel_at_period_end=true`; audit; analytics `subscription_cancelled` |
| `GET /billing/payments` | S | `limit, cursor` | list of `{id, amount_paise, currency, status, method, created_at, razorpay_invoice_id}` | — | — |

(Verify the Razorpay SDK method names/params against the official `razorpay` Python SDK before implementing.)

### Webhook

| Method & route | Auth | Request | Response | Side effects |
|---|---|---|---|---|
| `POST /webhooks/razorpay` | Signature (`X-Razorpay-Signature` = HMAC_SHA256(RAZORPAY_WEBHOOK_SECRET, raw_body)) | Razorpay event JSON; header `X-Razorpay-Event-Id` | `200` (also for duplicates); `400` invalid signature | insert `payment_webhook_events` (dedupe by event id); process: `subscription.authenticated`, `subscription.activated`, `subscription.charged` (payment row captured, period dates, plan active), `subscription.pending`, `subscription.halted` (plan → free after grace 3 days via job), `subscription.cancelled`, `subscription.completed`, `payment.failed` (payment row failed); state transitions only forward; audit `billing.*` |

## 13. API keys (`SO`)

| Method & route | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /api-keys` | S | — | `{data:[{id, name, key_prefix, scopes, created_at, last_used_at, expires_at}]}` | — |
| `POST /api-keys` | S+C | `{name, scopes?, expires_in_days?: 30|90|365|null}` | `201 {data:{…, secret}}` | `403 PLAN_FEATURE_UNAVAILABLE`, `409 LIMIT_REACHED` |
| `PATCH /api-keys/{id}` | S+C | `{name}` | `{data:api_key}` | `404` |
| `DELETE /api-keys/{id}` | S+C | — | `204` | `404` |

## 14. Analytics

| Method & route | Auth | Request | Response |
|---|---|---|---|
| `POST /analytics/events` | P or S (+C if session); Origin check | `{anonymous_id?, events:[{name, occurred_at, properties}] ≤ 20}` | `202` (drops non-allow-listed names/properties silently; no-op if opted out) |

## 15. Admin (`SO`; all mutations audited)

| Method & route | Role | Request | Response / side effects |
|---|---|---|---|
| `GET /admin/dashboard` | support | `range=24h|7d|30d` | KPIs: users total/new/active (DAU/WAU/MAU), messages, tokens, est. cost, error rate, p95 TTFT, active subscriptions, MRR (paise), queue depth |
| `GET /admin/users` | support | `q (email/name/id), status, role, plan, page, page_size, sort` | users list with usage counters |
| `GET /admin/users/{id}` | support | — | profile, plan, subscription, sessions count, usage 30d, flags, recent audit events (no content) |
| `PATCH /admin/users/{id}` | admin | `{status?: "active"|"suspended", suspended_reason?, role?, plan_key_override?}` + `reason` (required) | updated user; suspension revokes sessions; `404`, `409 CANNOT_MODIFY_SELF` (role/status of self) |
| `POST /admin/users/{id}/revoke-sessions` | admin | `{reason}` | `{revoked_count}` |
| `GET /admin/usage` | support | `from, to, group_by=day|model|kind|plan, user_id?` | aggregates from `usage_daily` incl. est. cost |
| `GET /admin/conversations` | support | `user_id?, from, to, page` | metadata only: id, user_id, title redacted by default (`title_visible=false`), message_count, model_key, created/last activity |
| `GET /admin/conversations/{id}` | support (title hidden); admin with `reveal_title=true&reason=…` | `reason` required when revealing | metadata; title reveal audited `admin.title.revealed` |
| `GET /admin/conversations/{id}/messages` | admin | `reason` (query, required, 10–500 chars) | full content; audit `admin.content.accessed` with reason; `422 REASON_REQUIRED` |
| `GET /admin/health` | support | — | dependency checks, Groq model verification report, queue depths, worker heartbeats, circuit states, sandbox runner health |
| `GET /admin/errors` | support | `from, to, source=groq|tools|files|webhooks` | aggregated error counts by code + recent failed items (ids) |
| `GET /admin/subscriptions` | support | `status, plan, page` | list |
| `GET /admin/payments` | support | `status, from, to, page` | list |
| `GET /admin/webhook-events` | support | `status=failed|processed, event_type, page` | list of `payment_webhook_events` (payload shown to admin only) |
| `POST /admin/webhook-events/{id}/reprocess` | admin | `{reason}` | reprocessed result; idempotent; audited `admin.webhook.reprocessed` |
| `GET /admin/audit-logs` | support | `actor_user_id, action, target_type, target_id, from, to, cursor` | list |
| `GET /admin/moderation/flags` | support | `status, category, page` | list |
| `PATCH /admin/moderation/flags/{id}` | support | `{status, resolution_note}` | updated flag |
| `GET /admin/settings` | admin | — | typed settings with current values |
| `PATCH /admin/settings/{key}` | admin | `{value, reason}` | validated; cache invalidated |
| `GET /admin/models` | support | — | registry entries incl. `groq_model_id`, verification status, admin-disabled flag, pricing |
| `PATCH /admin/models/{key}` | admin | `{enabled: bool, reason}` | writes `system_settings.disabled_model_keys` |
| `GET /admin/plans` | support | — | plans with limits |
| `PATCH /admin/plans/{key}` | admin | `{limits?, is_active?, description?, reason}` (price/razorpay id changes require a migration/runbook, not API) | validated via `PlanLimits` |
| `GET /admin/analytics` | support | `metric=funnel|retention|feature_usage, from, to` | `37_ANALYTICS.md` §6 |

Admin list endpoints accept `format=csv` to stream CSV (max 50,000 rows) — audited `admin.export`.
