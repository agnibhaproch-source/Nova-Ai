# 08 — Database Schema

Conventions from `07_DATABASE_ARCHITECTURE.md` apply. Notation:

- **PK** primary key, **FK→t.c (rule)** foreign key with ON DELETE rule, **UQ** unique, **IX** index, **CK** check.
- `D` = `EMBEDDING_DIMENSIONS` (fixed at migration time).
- All `created_at`/`updated_at` are `timestamptz NOT NULL DEFAULT now()` unless noted; `updated_at` is maintained by trigger `set_updated_at`.

Table list (25):

| # | Table | Aggregate owner |
|---|---|---|
| 1 | users | — |
| 2 | sessions | users |
| 3 | email_tokens | users |
| 4 | user_preferences | users |
| 5 | plans | — |
| 6 | conversations | users |
| 7 | messages | conversations |
| 8 | message_parts | messages |
| 9 | files | users |
| 10 | conversation_files | conversations/files |
| 11 | document_chunks | files |
| 12 | memories | users |
| 13 | tool_calls | messages |
| 14 | usage_records | users (SET NULL) |
| 15 | usage_daily | users |
| 16 | subscriptions | users (SET NULL) |
| 17 | payments | users (SET NULL) |
| 18 | payment_webhook_events | — |
| 19 | feedback | messages |
| 20 | api_keys | users |
| 21 | audit_logs | — |
| 22 | analytics_events | — |
| 23 | system_settings | — |
| 24 | moderation_flags | users |
| 25 | data_exports | users |

---

## 1. `users`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | Identity |
| email | citext | no | — | UQ partial `uq_users_email_active` on (email) WHERE deleted_at IS NULL; CK length ≤ 254 | Login identifier |
| email_verified_at | timestamptz | yes | NULL | — | Unused since ADR 0002 (no email verification); kept for compatibility |
| password_hash | text | no | — | — | Argon2id encoded hash |
| display_name | varchar(80) | no | — | CK char_length ≥ 1 | Shown in UI |
| avatar_storage_key | text | yes | NULL | — | S3 key of avatar image |
| role | text | no | 'user' | CK IN ('user','support','admin') | Authorization role |
| status | text | no | 'active' | CK IN ('active','suspended','deleted'); IX (status) | Account state |
| suspended_reason | text | yes | NULL | — | Admin-provided reason |
| plan_key | text | no | 'free' | FK→plans.key (RESTRICT); IX | Effective plan (denormalized from subscriptions) |
| failed_login_count | integer | no | 0 | CK ≥ 0 | Lockout counter (reset on success) |
| locked_until | timestamptz | yes | NULL | — | Lockout end |
| last_login_at | timestamptz | yes | NULL | — | Stats |
| onboarding_completed_at | timestamptz | yes | NULL | — | Onboarding gate |
| password_changed_at | timestamptz | no | now() | — | Session invalidation reference |
| created_at, updated_at | timestamptz | no | now() | IX (created_at) | — |
| deleted_at | timestamptz | yes | NULL | — | Deletion request time |

## 2. `sessions`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | Session id (also CSRF binding) |
| user_id | uuid | no | — | FK→users.id (CASCADE); IX (user_id) WHERE revoked_at IS NULL | Owner |
| token_hash | bytea | no | — | UQ | SHA-256 of cookie token (32 bytes) |
| created_at | timestamptz | no | now() | — | — |
| last_seen_at | timestamptz | no | now() | — | Updated at most once per 5 min |
| expires_at | timestamptz | no | — | IX | Absolute expiry (created + SESSION_TTL_DAYS) |
| revoked_at | timestamptz | yes | NULL | — | Revocation |
| revoked_reason | text | yes | NULL | CK IN ('logout','user_revoked','password_changed','admin_revoked','account_suspended','account_deleted','expired_idle') | — |
| ip_address | inet | yes | NULL | — | Creation IP (nulled after 180 d) |
| user_agent | text | yes | NULL | CK length ≤ 512 | Raw UA (truncated) |
| device_label | varchar(120) | yes | NULL | — | e.g., "Chrome on macOS" |

## 3. `email_tokens`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | no | — | FK→users.id (CASCADE); IX | Owner |
| purpose | text | no | — | CK IN ('verify_email','reset_password') | Token type |
| token_hash | bytea | no | — | UQ | SHA-256 of emailed token |
| expires_at | timestamptz | no | — | — | 24 h verify, 60 min reset |
| consumed_at | timestamptz | yes | NULL | — | Single use |
| created_at | timestamptz | no | now() | — | — |

## 4. `user_preferences`

| Column | Type | Null | Default | Constraints | Purpose |
|---|---|---|---|---|---|
| user_id | uuid | no | — | PK, FK→users.id (CASCADE) | 1:1 with users |
| theme | text | no | 'system' | CK IN ('system','light','dark') | UI theme |
| default_model_key | text | yes | NULL | — (validated against registry in app) | Default model; NULL = registry default |
| custom_instructions | text | yes | NULL | CK char_length ≤ 1500 | "How should Nova respond" |
| about_user | text | yes | NULL | CK char_length ≤ 1500 | "What should Nova know about you" |
| memory_enabled | boolean | no | true | — | Long-term memory use + extraction |
| web_search_enabled | boolean | no | true | — | Allow web_search tool |
| code_execution_enabled | boolean | no | true | — | Allow code_execution tool |
| send_with_enter | boolean | no | true | — | Composer behavior |
| locale | varchar(16) | no | 'en' | — | UI locale |
| timezone | varchar(64) | no | 'UTC' | — | IANA TZ for grouping/dates |
| tts_voice | varchar(64) | yes | NULL | — | Preferred TTS voice id |
| analytics_opt_out | boolean | no | false | — | PRV-007 |
| created_at, updated_at | timestamptz | no | now() | — | — |

## 5. `plans`

| Column | Type | Null | Default | Constraints | Purpose |
|---|---|---|---|---|---|
| key | text | no | — | PK; CK IN ('free','plus','pro') | Plan identifier |
| name | varchar(40) | no | — | — | Display name |
| description | text | no | '' | — | Marketing copy |
| price_paise | integer | no | 0 | CK ≥ 0 | Monthly price in paise (INR) |
| currency | char(3) | no | 'INR' | — | — |
| razorpay_plan_id | text | yes | NULL | UQ | Razorpay plan (NULL for free) |
| limits | jsonb | no | — | validated by `PlanLimits` schema | See `35_USAGE_TRACKING.md` §5 |
| is_active | boolean | no | true | — | Purchasable |
| sort_order | smallint | no | 0 | — | Display order |
| created_at, updated_at | timestamptz | no | now() | — | — |

Seeded by migration `0005_seed_plans` (values in `35_USAGE_TRACKING.md` §5); editable by admins.

## 6. `conversations`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | no | — | FK→users.id (CASCADE) | Owner |
| title | varchar(200) | no | 'New chat' | CK char_length ≥ 1; IX GIN (title gin_trgm_ops) | Title |
| title_source | text | no | 'default' | CK IN ('default','generated','user') | Prevents overwriting user titles |
| model_key | text | no | — | — | Selected model alias |
| current_leaf_message_id | uuid | yes | NULL | FK→messages.id (SET NULL) DEFERRABLE INITIALLY DEFERRED | Active branch tip |
| summary | text | yes | NULL | — | Rolling summary of older turns (16 §6) |
| summary_through_message_id | uuid | yes | NULL | FK→messages.id (SET NULL) | Last message covered by summary |
| summary_token_count | integer | no | 0 | CK ≥ 0 | — |
| pinned_at | timestamptz | yes | NULL | — | Pinned ordering |
| archived_at | timestamptz | yes | NULL | — | Archived flag |
| last_message_at | timestamptz | no | now() | — | Sidebar ordering |
| message_count | integer | no | 0 | CK ≥ 0 | Stats |
| created_at, updated_at | timestamptz | no | now() | — | — |
| deleted_at | timestamptz | yes | NULL | — | Trash |

Indexes:
- `ix_conversations_user_active` ON (user_id, pinned_at DESC NULLS LAST, last_message_at DESC) WHERE deleted_at IS NULL AND archived_at IS NULL
- `ix_conversations_user_archived` ON (user_id, archived_at DESC) WHERE deleted_at IS NULL AND archived_at IS NOT NULL
- `ix_conversations_user_deleted` ON (user_id, deleted_at DESC) WHERE deleted_at IS NOT NULL

## 7. `messages`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| conversation_id | uuid | no | — | FK→conversations.id (CASCADE) | Parent conversation |
| user_id | uuid | no | — | FK→users.id (CASCADE) | Denormalized owner for authz |
| parent_message_id | uuid | yes | NULL | FK→messages.id (CASCADE); IX | Tree parent (NULL = root) |
| role | text | no | — | CK IN ('system','user','assistant','tool') | Author role (12 §2) |
| status | text | no | 'completed' | CK IN ('pending','streaming','completed','cancelled','failed') | Lifecycle |
| content_text | text | no | '' | — | Denormalized plain text of text/code parts (search, context) |
| content_tsv | tsvector | — | GENERATED ALWAYS AS (to_tsvector('simple', left(content_text, 100000))) STORED | IX GIN | FTS |
| model_key | text | yes | NULL | — | Assistant only |
| groq_model_id | text | yes | NULL | — | Actual Groq model used |
| finish_reason | text | yes | NULL | CK IN ('stop','length','tool_calls','cancelled','error','content_filter') | Final reason |
| error_code | text | yes | NULL | — | `32_ERROR_HANDLING.md` code |
| sibling_index | integer | no | 0 | CK ≥ 0 | Order among siblings (0-based) |
| idempotency_key | varchar(128) | yes | NULL | UQ (conversation_id, idempotency_key) WHERE idempotency_key IS NOT NULL | Duplicate prevention |
| prompt_tokens | integer | yes | NULL | — | Sum over Groq calls for this message |
| completion_tokens | integer | yes | NULL | — | — |
| time_to_first_token_ms | integer | yes | NULL | — | Metrics |
| latency_ms | integer | yes | NULL | — | Total generation time |
| metadata | jsonb | no | '{}' | — | Context stats: used memory ids, chunk ids, tool iterations, truncation flags |
| created_at, updated_at | timestamptz | no | now() | — | — |
| completed_at | timestamptz | yes | NULL | — | Terminal time |

Indexes: `ix_messages_conversation_created` (conversation_id, created_at); `ix_messages_parent` (parent_message_id, sibling_index); `ix_messages_status_streaming` (updated_at) WHERE status IN ('pending','streaming') (reaper).

## 8. `message_parts`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| message_id | uuid | no | — | FK→messages.id (CASCADE) | Parent |
| position | smallint | no | — | UQ (message_id, position); CK ≥ 0 | Order |
| type | text | no | — | CK IN ('text','image','file','citation','tool_call','tool_result','code') | Part type (12 §3) |
| text_content | text | yes | NULL | — | For text/code |
| data | jsonb | no | '{}' | — | Type-specific payload (12 §3) |
| file_id | uuid | yes | NULL | FK→files.id (SET NULL); IX | image/file parts |
| tool_call_id | uuid | yes | NULL | FK→tool_calls.id (SET NULL) | tool_call/tool_result/code parts |
| created_at | timestamptz | no | now() | — | — |

## 9. `files`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | no | — | FK→users.id (CASCADE) | Owner |
| original_filename | varchar(255) | no | — | — | As uploaded (display only) |
| extension | varchar(16) | no | — | — | Lower-case, no dot |
| declared_mime_type | varchar(127) | no | — | — | From client |
| detected_mime_type | varchar(127) | yes | NULL | — | libmagic result |
| size_bytes | bigint | no | — | CK > 0 | Declared, then verified |
| sha256 | char(64) | yes | NULL | IX (user_id, sha256) | Dedup/integrity |
| storage_key | text | no | — | UQ | `users/{user_id}/files/{file_id}` |
| kind | text | no | — | CK IN ('document','image','audio') | Category |
| purpose | text | no | 'attachment' | CK IN ('attachment','avatar','voice') | Usage |
| status | text | no | 'pending_upload' | CK IN ('pending_upload','uploaded','scanning','processing','ready','failed','rejected','deleted') | Lifecycle (18 §7) |
| error_code | text | yes | NULL | — | e.g., FILE_TYPE_MISMATCH |
| error_message | text | yes | NULL | — | User-safe message |
| page_count | integer | yes | NULL | — | Pages/slides/sheets |
| token_count | integer | yes | NULL | — | Extracted text tokens |
| chunk_count | integer | no | 0 | — | Indexed chunks |
| metadata | jsonb | no | '{}' | — | Extraction info (title, author, sheet names, image width/height) |
| processed_at | timestamptz | yes | NULL | — | Ready/failed time |
| created_at, updated_at | timestamptz | no | now() | — | — |
| deleted_at | timestamptz | yes | NULL | — | Soft delete |

Indexes: `ix_files_user_created` (user_id, created_at DESC) WHERE deleted_at IS NULL; `ix_files_status_pending` (status, created_at) WHERE status IN ('pending_upload','uploaded','scanning','processing').

## 10. `conversation_files`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| conversation_id | uuid | no | — | PK part; FK→conversations.id (CASCADE) | — |
| file_id | uuid | no | — | PK part; FK→files.id (CASCADE); IX (file_id) | — |
| attached_by_message_id | uuid | yes | NULL | FK→messages.id (SET NULL) | Message that attached it |
| created_at | timestamptz | no | now() | — | — |

## 11. `document_chunks`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| file_id | uuid | no | — | FK→files.id (CASCADE) | Source file |
| user_id | uuid | no | — | FK→users.id (CASCADE); IX (user_id, file_id) | Permission filter |
| chunk_index | integer | no | — | UQ (file_id, chunk_index) | Order within file |
| content | text | no | — | — | Chunk text |
| token_count | integer | no | — | CK > 0 | — |
| page_number | integer | yes | NULL | — | PDF page / slide number |
| sheet_name | varchar(128) | yes | NULL | — | XLSX sheet |
| section_title | varchar(300) | yes | NULL | — | Nearest heading |
| char_start | integer | no | — | — | Offset in normalized text |
| char_end | integer | no | — | CK char_end > char_start | — |
| content_tsv | tsvector | — | GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED | IX GIN | Hybrid search |
| embedding | vector(D) | yes | NULL | IX HNSW (embedding vector_cosine_ops) WITH (m=16, ef_construction=64) | Semantic search |
| embedding_model | varchar(200) | yes | NULL | — | Model that produced embedding |
| created_at | timestamptz | no | now() | — | — |

## 12. `memories`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | no | — | FK→users.id (CASCADE); IX (user_id, updated_at DESC) WHERE deleted_at IS NULL | Owner |
| content | varchar(500) | no | — | CK char_length ≥ 3 | Memory statement (third person: "Prefers TypeScript") |
| content_hash | char(64) | no | — | UQ (user_id, content_hash) WHERE deleted_at IS NULL | Exact dedupe (sha256 of normalized content) |
| category | text | no | 'other' | CK IN ('preference','biographical','project','instruction','other') | — |
| importance | smallint | no | 3 | CK BETWEEN 1 AND 5 | Retrieval weight |
| source | text | no | — | CK IN ('extracted','user_created') | Provenance |
| source_conversation_id | uuid | yes | NULL | FK→conversations.id (SET NULL) | — |
| source_message_id | uuid | yes | NULL | FK→messages.id (SET NULL) | — |
| embedding | vector(D) | yes | NULL | IX HNSW (vector_cosine_ops) | Relevance search |
| embedding_model | varchar(200) | yes | NULL | — | — |
| use_count | integer | no | 0 | — | Times injected into context |
| last_used_at | timestamptz | yes | NULL | — | Retention scoring |
| created_at, updated_at | timestamptz | no | now() | — | — |
| deleted_at | timestamptz | yes | NULL | — | Soft delete (7-day undo) |

## 13. `tool_calls`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| message_id | uuid | no | — | FK→messages.id (CASCADE); IX | Assistant message that requested it |
| conversation_id | uuid | no | — | FK→conversations.id (CASCADE) | — |
| user_id | uuid | no | — | FK→users.id (CASCADE); IX (user_id, created_at DESC) | Owner / quotas |
| provider_tool_call_id | varchar(128) | no | — | — | Groq-assigned tool call id |
| iteration | smallint | no | 0 | CK BETWEEN 0 AND 10 | Tool loop iteration |
| tool_name | varchar(64) | no | — | IX (tool_name, created_at) | Registered tool |
| arguments | jsonb | no | '{}' | — | Validated arguments |
| status | text | no | 'pending' | CK IN ('pending','running','succeeded','failed','timed_out','denied') | Lifecycle |
| result | jsonb | yes | NULL | — | Normalized result (size-capped 256 KB) |
| error_code | text | yes | NULL | — | — |
| error_message | text | yes | NULL | — | Safe message |
| started_at | timestamptz | yes | NULL | — | — |
| completed_at | timestamptz | yes | NULL | — | — |
| latency_ms | integer | yes | NULL | — | — |
| created_at | timestamptz | no | now() | — | — |

## 14. `usage_records`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | yes | — | FK→users.id (SET NULL); IX (user_id, created_at DESC) | Owner (NULL after deletion) |
| api_key_id | uuid | yes | NULL | FK→api_keys.id (SET NULL) | When via API key |
| conversation_id | uuid | yes | NULL | FK→conversations.id (SET NULL) | — |
| message_id | uuid | yes | NULL | FK→messages.id (SET NULL) | — |
| request_id | varchar(64) | no | — | — | Correlation |
| kind | text | no | — | CK IN ('chat','title','summary','memory_extraction','embedding','stt','tts','web_search','code_execution','eval') | Operation |
| provider | text | no | — | CK IN ('groq','embeddings','search','sandbox') | Upstream |
| model_id | varchar(200) | yes | NULL | — | groq_model_id / embedding model |
| model_key | varchar(64) | yes | NULL | — | Registry alias |
| prompt_tokens | integer | no | 0 | — | — |
| completion_tokens | integer | no | 0 | — | — |
| total_tokens | integer | no | 0 | — | — |
| audio_seconds | numeric(10,2) | yes | NULL | — | STT/TTS |
| characters | integer | yes | NULL | — | TTS input chars |
| latency_ms | integer | no | 0 | — | — |
| time_to_first_token_ms | integer | yes | NULL | — | — |
| status | text | no | — | CK IN ('success','error','cancelled') | — |
| error_code | text | yes | NULL | — | — |
| estimated_cost_usd_micros | bigint | yes | NULL | — | NULL when price unknown |
| created_at | timestamptz | no | now() | IX (created_at); IX (kind, created_at) | — |

## 15. `usage_daily`

| Column | Type | Null | Default | Constraints | Purpose |
|---|---|---|---|---|---|
| user_id | uuid | no | — | PK part; FK→users.id (CASCADE) | — |
| day | date | no | — | PK part | UTC day |
| kind | text | no | — | PK part | Same enum as usage_records.kind |
| model_key | varchar(64) | no | '' | PK part | '' when N/A |
| request_count | integer | no | 0 | — | — |
| error_count | integer | no | 0 | — | — |
| prompt_tokens | bigint | no | 0 | — | — |
| completion_tokens | bigint | no | 0 | — | — |
| estimated_cost_usd_micros | bigint | no | 0 | — | — |
| updated_at | timestamptz | no | now() | — | — |

Maintained by `aggregate_usage_daily` (every 5 min, upsert from `usage_records` since watermark stored in Redis `nova:{env}:usage:agg_watermark`). Global index (day, kind) for admin charts.

## 16. `subscriptions`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | yes | — | FK→users.id (SET NULL); IX; UQ partial (user_id) WHERE status IN ('created','authenticated','active','pending','halted') | One live subscription per user |
| plan_key | text | no | — | FK→plans.key (RESTRICT) | — |
| razorpay_subscription_id | varchar(64) | no | — | UQ | Razorpay `sub_...` |
| razorpay_customer_id | varchar(64) | yes | NULL | — | — |
| status | text | no | 'created' | CK IN ('created','authenticated','active','pending','halted','cancelled','completed','expired') | Mirrors Razorpay states |
| current_period_start | timestamptz | yes | NULL | — | — |
| current_period_end | timestamptz | yes | NULL | — | Access until |
| cancel_at_period_end | boolean | no | false | — | — |
| cancelled_at | timestamptz | yes | NULL | — | — |
| ended_at | timestamptz | yes | NULL | — | — |
| created_at, updated_at | timestamptz | no | now() | — | — |

## 17. `payments`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | yes | — | FK→users.id (SET NULL); IX (user_id, created_at DESC) | — |
| subscription_id | uuid | yes | NULL | FK→subscriptions.id (SET NULL); IX | — |
| razorpay_payment_id | varchar(64) | no | — | UQ | `pay_...` |
| razorpay_invoice_id | varchar(64) | yes | NULL | — | `inv_...` |
| razorpay_order_id | varchar(64) | yes | NULL | — | — |
| amount_paise | bigint | no | — | CK ≥ 0 | — |
| currency | char(3) | no | 'INR' | — | — |
| status | text | no | — | CK IN ('created','authorized','captured','failed','refunded') | — |
| method | varchar(32) | yes | NULL | — | card/upi/netbanking... |
| failure_reason | text | yes | NULL | — | — |
| captured_at | timestamptz | yes | NULL | — | — |
| created_at, updated_at | timestamptz | no | now() | — | — |

No card/UPI details stored.

## 18. `payment_webhook_events`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| provider | text | no | 'razorpay' | CK IN ('razorpay') | — |
| event_id | varchar(128) | no | — | UQ (provider, event_id) | `X-Razorpay-Event-Id` header — idempotency |
| event_type | varchar(64) | no | — | IX | e.g., subscription.charged |
| payload | jsonb | no | — | — | Raw event body |
| processed_at | timestamptz | yes | NULL | — | NULL = pending/failed |
| processing_error | text | yes | NULL | — | — |
| received_at | timestamptz | no | now() | — | — |

## 19. `feedback`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | no | — | FK→users.id (CASCADE); UQ (user_id, message_id) | — |
| message_id | uuid | no | — | FK→messages.id (CASCADE); IX | Assistant message |
| conversation_id | uuid | no | — | FK→conversations.id (CASCADE) | — |
| rating | text | no | — | CK IN ('up','down') | — |
| reasons | text[] | no | '{}' | CK reasons <@ ARRAY['inaccurate','not_helpful','harmful','incomplete','wrong_citation','too_long','too_short','other'] | — |
| comment | text | yes | NULL | CK char_length ≤ 2000 | — |
| created_at, updated_at | timestamptz | no | now() | IX (created_at) | — |

## 20. `api_keys`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | no | — | FK→users.id (CASCADE); IX (user_id) WHERE revoked_at IS NULL | Owner |
| name | varchar(80) | no | — | — | User label |
| key_prefix | char(16) | no | — | IX | First 16 chars `nova_sk_` + 8 chars (display & lookup hint) |
| key_hash | bytea | no | — | UQ | HMAC-SHA256(AUTH_SECRET, full key) |
| scopes | text[] | no | '{chat:write,conversations:read}' | CK scopes <@ ARRAY['chat:write','conversations:read','conversations:write','files:read','files:write','memories:read','usage:read'] | Permissions |
| last_used_at | timestamptz | yes | NULL | — | Updated at most once/min |
| last_used_ip | inet | yes | NULL | — | — |
| expires_at | timestamptz | yes | NULL | — | Optional expiry |
| revoked_at | timestamptz | yes | NULL | — | — |
| created_at | timestamptz | no | now() | — | — |

Max 10 active keys per user (enforced in service).

## 21. `audit_logs`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| actor_user_id | uuid | yes | NULL | FK→users.id (SET NULL); IX (actor_user_id, created_at DESC) | Who |
| actor_type | text | no | — | CK IN ('user','admin','support','system','api_key','webhook') | — |
| action | varchar(64) | no | — | IX (action, created_at DESC) | Dotted action (`38_LOGGING.md` §7) |
| target_type | varchar(32) | yes | NULL | — | e.g., user, conversation |
| target_id | uuid | yes | NULL | IX (target_type, target_id) | — |
| reason | text | yes | NULL | — | Required for admin content access & suspensions |
| ip_address | inet | yes | NULL | — | — |
| user_agent | text | yes | NULL | — | — |
| request_id | varchar(64) | yes | NULL | — | — |
| metadata | jsonb | no | '{}' | — | Non-sensitive details (never secrets/content) |
| created_at | timestamptz | no | now() | IX (created_at DESC) | — |

App role has INSERT/SELECT only.

## 22. `analytics_events`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| event_name | varchar(64) | no | — | IX (event_name, occurred_at) | Allow-listed name (37 §3) |
| user_id | uuid | yes | NULL | FK→users.id (SET NULL); IX (user_id, occurred_at) | — |
| anonymous_id | varchar(64) | yes | NULL | — | Pre-signup visitor id (first-party cookie `nova_aid`) |
| source | text | no | — | CK IN ('web','api','worker') | — |
| properties | jsonb | no | '{}' | — | Allow-listed properties, no content |
| occurred_at | timestamptz | no | — | — | Client or server time |
| received_at | timestamptz | no | now() | — | — |

## 23. `system_settings`

| Column | Type | Null | Default | Constraints | Purpose |
|---|---|---|---|---|---|
| key | varchar(64) | no | — | PK | e.g., `signups_enabled` |
| value | jsonb | no | — | validated by typed registry (36 §11) | — |
| updated_by | uuid | yes | NULL | FK→users.id (SET NULL) | — |
| updated_at | timestamptz | no | now() | — | — |

## 24. `moderation_flags`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | no | — | FK→users.id (CASCADE); IX | Subject user |
| conversation_id | uuid | yes | NULL | FK→conversations.id (SET NULL) | — |
| message_id | uuid | yes | NULL | FK→messages.id (SET NULL) | — |
| source | text | no | — | CK IN ('user_report','automated','admin') | — |
| category | text | no | — | CK IN ('abuse','spam','illegal','self_harm','harassment','rate_abuse','payment_fraud','other') | — |
| details | text | yes | NULL | CK ≤ 2000 chars | Reporter note / rule id |
| status | text | no | 'open' | CK IN ('open','reviewing','resolved','dismissed'); IX (status, created_at) | — |
| resolved_by | uuid | yes | NULL | FK→users.id (SET NULL) | — |
| resolution_note | text | yes | NULL | — | — |
| created_at, updated_at | timestamptz | no | now() | — | — |
| resolved_at | timestamptz | yes | NULL | — | — |

## 25. `data_exports`

| Column | Type | Null | Default | Constraints / Index | Purpose |
|---|---|---|---|---|---|
| id | uuid | no | gen_random_uuid() | PK | — |
| user_id | uuid | no | — | FK→users.id (CASCADE); IX (user_id, created_at DESC) | — |
| status | text | no | 'queued' | CK IN ('queued','running','ready','failed','expired') | — |
| storage_key | text | yes | NULL | — | `users/{uid}/exports/{id}.zip` |
| size_bytes | bigint | yes | NULL | — | — |
| error_message | text | yes | NULL | — | — |
| expires_at | timestamptz | yes | NULL | — | ready + 24 h |
| created_at, updated_at | timestamptz | no | now() | — | — |
| completed_at | timestamptz | yes | NULL | — | — |

Max 1 export per user per 24 h.

---

## 26. Relationships

```
plans 1───* users 1───1 user_preferences
            │  1───* sessions, email_tokens, api_keys, memories, files, feedback, data_exports, moderation_flags
            │  1───* conversations 1───* messages 1───* message_parts
            │                     │        │ 1───* tool_calls
            │                     │        └── parent_message_id (self, tree)
            │                     *───* files (via conversation_files)
            │  files 1───* document_chunks
            │  1───* subscriptions 1───* payments      (SET NULL on user delete)
            │  1───* usage_records / usage_daily
audit_logs, analytics_events, payment_webhook_events, system_settings: loosely coupled
```

Ownership invariants enforced in services (and verified by tests):
- `messages.user_id = conversations.user_id` of its conversation.
- `document_chunks.user_id = files.user_id`.
- `conversation_files` may only link a conversation and file with the same `user_id`.
- `message_parts.file_id` must reference a file owned by the message's user.
- `tool_calls.user_id = messages.user_id`.

## 27. Migration order

`0001_extensions` → `0002_updated_at_trigger` → `0003_users_auth` (users, sessions, email_tokens, user_preferences, plans + FK) → `0004_audit_system` (audit_logs, system_settings, analytics_events) → `0005_seed_plans` → `0006_chat` (conversations, messages, message_parts, feedback) → `0007_usage` (usage_records, usage_daily) → `0008_files` (files, conversation_files) → `0009_moderation_exports` (moderation_flags, data_exports) → `0010_chunks_vector` (document_chunks + HNSW) → `0011_memories` → `0012_tool_calls` → `0013_billing` (subscriptions, payments, payment_webhook_events) → `0014_api_keys`. Phases in `53_IMPLEMENTATION_PHASES.md` map to these.

Forward references: `message_parts.tool_call_id` is created as a plain nullable `uuid` in `0006_chat`; its FK constraint is added in `0012_tool_calls`. `usage_records.api_key_id` is created in `0007_usage` as plain `uuid`; its FK is added in `0014_api_keys`. `message_parts.file_id` FK is added in `0008_files`.
