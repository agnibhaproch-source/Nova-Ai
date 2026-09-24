# 10 — User System

## 1. User profile

Fields exposed by `GET /api/v1/users/me`:

```json
{
  "data": {
    "id": "uuid",
    "email": "priya@example.com",
    "display_name": "Priya",
    "avatar_url": "https://<presigned-get>|null",
    "role": "user",
    "plan_key": "free",
    "created_at": "2026-01-01T10:00:00Z",
    "onboarding_completed": true
  }
}
```

`PATCH /api/v1/users/me` accepts `{display_name?}`. Validation: trimmed, 1–80 chars, no control characters.

### Avatar
1. Client uploads an image through the file pipeline with `purpose='avatar'` (`18_FILE_UPLOADS.md`; allowed: PNG/JPEG/WEBP ≤ 2 MB).
2. `PUT /api/v1/users/me/avatar {file_id}` → verifies ownership, `kind='image'`, `status='ready'` → worker `process_file` for avatars re-encodes to 256×256 WEBP (Pillow) stored at `users/{uid}/avatar/{file_id}.webp`; `users.avatar_storage_key` updated; previous avatar object deleted.
3. `DELETE /api/v1/users/me/avatar` clears it.
4. `avatar_url` is a presigned GET URL valid 1 h, generated on read (cached in Redis 50 min).

## 2. Preferences

`GET/PATCH /api/v1/users/me/preferences` (columns in `08_DATABASE_SCHEMA.md` §4).

| Field | Validation | Effect |
|---|---|---|
| theme | enum | Applied client-side; persisted for cross-device |
| default_model_key | must be enabled in registry **and** allowed by plan | New conversations use it |
| custom_instructions | ≤ 1500 chars | Injected into system prompt (`16_CONTEXT_MANAGEMENT.md` §3) |
| about_user | ≤ 1500 chars | Injected into system prompt |
| memory_enabled | bool | Disables memory retrieval **and** extraction immediately |
| web_search_enabled | bool | Controls availability of `web_search` tool |
| code_execution_enabled | bool | Controls `code_execution` tool |
| send_with_enter | bool | Composer key behavior |
| locale | BCP-47 in supported set (`en` initially) | UI language |
| timezone | valid IANA name (`zoneinfo.available_timezones()`) | Sidebar date grouping, system prompt date |
| tts_voice | must be in configured voices list | Voice mode |
| analytics_opt_out | bool | Stops product analytics for the user |

Changes to preferences invalidate the Redis context cache key `nova:{env}:ctx:prefs:{user_id}`.

## 3. Account settings UI map

| Route | Section | Contents |
|---|---|---|
| `/settings/general` | General | Theme, language, send-with-Enter, default model, timezone |
| `/settings/profile` | Profile | Display name, avatar, email (read-only) |
| `/settings/personalization` | Personalization | Custom instructions, about me, memory toggle, memory list management |
| `/settings/data` | Data controls | Export data, archived chats, trash, delete all chats, analytics opt-out |
| `/settings/security` | Security | Change password, active sessions, sign out other devices, delete account |
| `/settings/api-keys` | API keys | List/create/revoke keys |
| `/settings/billing` | Billing | Plan, upgrade/cancel, payment history |
| `/settings/usage` | Usage | Quota meters, usage charts |

## 4. Privacy

- Users see exactly what is stored: conversations, files, memories, sessions, API keys, usage, payments.
- No conversation content is used for training or shared with third parties other than Groq (for inference), the embeddings service (self-hosted), and the search provider (only the query string generated for search).
- Analytics excludes content (`37_ANALYTICS.md`).
- The privacy page (`/privacy`, static marketing page) documents the above; its content is owned by legal and is out of scope for engineering beyond rendering.

## 5. Onboarding

- Shown when `onboarding_completed_at IS NULL` after login (redirect from `/chat` to `/onboarding`).
- Step 1: "What will you use Nova for?" multi-select chips (Writing, Coding, Research, Studying, Work documents, Other) → stored as analytics property only (`onboarding_completed` event) — not persisted in DB.
- Step 2: optional custom instructions textarea + memory toggle explanation.
- `POST /api/v1/users/me/onboarding/complete {custom_instructions?, memory_enabled}` sets preferences and `onboarding_completed_at`.
- "Skip" calls the same endpoint with no changes.

## 6. Sessions management

`GET /api/v1/users/me/sessions` returns active sessions:

```json
{"data":[{"id":"uuid","device_label":"Chrome on macOS","ip_address":"203.0.113.4",
          "created_at":"...","last_seen_at":"...","is_current":true}]}
```

- `DELETE /api/v1/users/me/sessions/{id}` — revoke one (cannot target another user's session → 404).
- `POST /api/v1/users/me/sessions/revoke-others` — revoke all except current.
- Both audited.

## 7. API keys (user-facing)

- `POST /api/v1/api-keys {name, scopes?, expires_in_days?}` (session auth only, plan must allow API access: `plans.limits.api_access = true` — free: false, plus/pro: true).
- Response includes `secret` **once**: `{"data": {"id","name","key_prefix","scopes","created_at","expires_at","secret":"nova_sk_..."}}`.
- `GET /api/v1/api-keys` lists without secrets. `PATCH /api/v1/api-keys/{id} {name}`. `DELETE /api/v1/api-keys/{id}` revokes (irreversible).
- Max 10 active keys. Usage via API keys counts against the owner's quotas and has its own rate-limit bucket (`34_RATE_LIMITING.md`).
- UI shows key prefix, name, scopes, created, last used, expiry; "Copy" only in the creation dialog, which warns "You won't see this key again."

## 8. Account deletion

`DELETE /api/v1/users/me` with body `{password, confirmation: "DELETE"}` (session auth + CSRF + password verification).

Transaction:
1. Verify password → else `401 INVALID_CREDENTIALS`.
2. Cancel live Razorpay subscription via `BillingService.cancel(immediately=True)` (API call before DB txn; failure → `502 PAYMENT_PROVIDER_ERROR`, deletion aborted, user told to retry).
3. `users.status='deleted'`, `deleted_at=now()`, email left intact until purge (unique index is partial on `deleted_at IS NULL`, so the email can re-register immediately).
4. Revoke all sessions (`account_deleted`); revoke all API keys.
5. Audit `user.deleted` (actor = user).
6. After commit: enqueue `purge_user(user_id)`; clear cookies; `204`.

`purge_user` job (idempotent): delete S3 prefix `users/{user_id}/` (batched `DeleteObjects` of 1000), then `DELETE FROM users WHERE id=:id` (cascades; financial/audit rows SET NULL). Must complete within 24 h; failures retried and alerted (`39_MONITORING.md`).

## 9. Data export

`POST /api/v1/users/me/exports` → `202 {data:{export}}` (max 1 per 24 h → `429 EXPORT_RATE_LIMITED`).

Worker `build_export(export_id)`:
- Streams into a ZIP (`zipfile` writing to a temp file on worker disk, ≤ 2 GB):
  - `profile.json` (user + preferences)
  - `conversations/{conversation_id}.json` — conversation metadata + all messages (all branches) with parts, tool calls, citations
  - `memories.json`
  - `files.json` (metadata) + `files/{file_id}-{sanitized_name}` original objects (optional flag `include_files`, default true, skipped if total > 1.5 GB with note in `README.txt`)
  - `usage.json` (daily aggregates), `payments.json`
  - `README.txt` describing format
- Upload to `users/{uid}/exports/{export_id}.zip`; `status='ready'`, `expires_at=now()+24h`; email link to `/settings/data` (download via `GET /api/v1/users/me/exports/{id}/download` → 302 presigned URL, 5 min).
- Audit `user.export.requested` and `user.export.downloaded`.

## 10. Memory controls (summary; full spec `17_MEMORY_SYSTEM.md`)

- Toggle: `user_preferences.memory_enabled`.
- List/search/edit/delete individual memories; "Delete all memories" with confirmation.
- Toast after extraction ("Memory updated") with link to manage.
- Deleting a memory removes it from future context immediately (cache invalidation).

## 11. Delete all chats

`POST /api/v1/conversations/bulk-delete {"all": true}` or `{"conversation_ids": [...]}` (≤ 100) → soft-deletes (moves to trash). Settings "Delete all chats" dialog explains the 30-day trash.
