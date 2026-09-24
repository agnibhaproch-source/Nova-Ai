# 07 — Database Architecture

## 1. PostgreSQL topology

- **Version:** PostgreSQL 16 (managed in staging/production; `pgvector/pgvector:pg16` image locally).
- **Extensions** (created by migration `0001_extensions` and by `infra/docker/postgres/init/001_extensions.sql` for dev):
  ```sql
  CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid(), digest()
  CREATE EXTENSION IF NOT EXISTS citext;     -- case-insensitive email
  CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- trigram search on titles
  CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector
  ```
- **Database:** single database `nova`, single schema `public`.
- **Roles:**
  - `nova_migrator` — owns tables; used only by Alembic in the release step.
  - `nova_app` — `SELECT, INSERT, UPDATE, DELETE` on all tables except `audit_logs` where it has `SELECT, INSERT` only (append-only enforcement). Used by api and worker.
  - `nova_readonly` — `SELECT` for analytics/BI and admin read replicas (Phase 11).
- **Production:** primary + 1 synchronous-standby (HA, managed failover) + optional read replica (Phase 11) for admin analytics queries.

## 2. Connection management

- Driver: `asyncpg` via SQLAlchemy `create_async_engine(DATABASE_URL, ...)`.
- Per-process pool: `pool_size=DATABASE_POOL_SIZE` (default 10), `max_overflow=DATABASE_MAX_OVERFLOW` (default 5), `pool_timeout=DATABASE_POOL_TIMEOUT` (default 10 s), `pool_pre_ping=True`, `pool_recycle=1800`.
- Worker processes use a separate smaller pool (`pool_size=5`).
- Budget: `(api_instances × gunicorn_workers × (pool_size+max_overflow)) + (worker_instances × 5) ≤ 0.8 × max_connections`. Above ~1,000 users introduce **PgBouncer in transaction mode**; then set `connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0}` for asyncpg compatibility (see `49_SCALABILITY.md`).
- Statement timeout: `SET statement_timeout = '15s'` via `connect_args={"server_settings": {"statement_timeout": "15000", "application_name": "nova-api"}}`. Workers use `60000` ms. `idle_in_transaction_session_timeout = '30s'` set at role level.

## 3. Session and transaction model

- One `AsyncSession` per HTTP request (dependency `get_db`), `expire_on_commit=False`.
- Services own transaction boundaries via `UnitOfWork`:
  ```python
  async with uow.begin():           # BEGIN ... COMMIT / ROLLBACK
      msg = await messages.insert(...)
      uow.after_commit(lambda: queue.enqueue("process_file", file_id))
  ```
- `after_commit` callbacks run only after a successful commit (job enqueueing, cache invalidation, analytics).
- Default isolation `READ COMMITTED`. Use `SELECT ... FOR UPDATE` for: subscription state transitions, quota reconciliation rows, conversation `current_leaf_message_id` updates during concurrent submits.
- Long operations (Groq streaming) **must not** hold a transaction open. The generation runner uses short transactions for each checkpoint.
- Optimistic concurrency where needed via `updated_at` compare-and-set (e.g., memory edits).

## 4. Migrations (Alembic)

- Location: `apps/api/alembic/versions/`, filename `YYYYMMDD_HHMM_<slug>.py`, revision IDs auto.
- Every model change ⇒ autogenerate + **manual review**; autogenerate misses: extension-specific indexes (HNSW), generated columns, CHECK constraints, partial indexes — write them explicitly with `op.execute` or `op.create_index(..., postgresql_where=...)`.
- **Expand/contract** for zero downtime:
  1. Expand: add nullable column/new table/new index `CONCURRENTLY` (use `with op.get_context().autocommit_block():`).
  2. Deploy code writing both old and new.
  3. Backfill via worker job in batches of 1,000 rows.
  4. Contract (later release): add NOT NULL/drop old column.
- Never edit a merged migration. Never drop a column in the same release that stops using it.
- `alembic upgrade head` runs as a one-off release task before new app instances start (`47_DEPLOYMENT.md` §5). App startup **checks** that the DB revision equals the code's head and refuses to start otherwise (`readyz` fails).
- Downgrade functions are written for every migration but production rollback prefers roll-forward.

## 5. Naming conventions

SQLAlchemy `MetaData(naming_convention=...)`:

```python
NAMING_CONVENTION = {
  "ix": "ix_%(table_name)s_%(column_0_N_name)s",
  "uq": "uq_%(table_name)s_%(column_0_N_name)s",
  "ck": "ck_%(table_name)s_%(constraint_name)s",
  "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
  "pk": "pk_%(table_name)s",
}
```

- Tables: plural snake_case (`conversation_files`). Columns: snake_case. Booleans: `is_*`/`*_enabled`. Timestamps: `*_at`. Foreign keys: `<singular>_id`.
- Enumerations: `text` column + `CHECK (col IN (...))` named `ck_<table>_<col>_valid` (easier to evolve than native enums). Python side uses `StrEnum`.

## 6. Primary keys and IDs

- `id uuid PRIMARY KEY DEFAULT gen_random_uuid()` on all entity tables.
- Exceptions: `user_preferences` (PK = `user_id`), `plans` (PK = `key text`), `system_settings` (PK = `key text`), `conversation_files` (composite PK), `usage_daily` (composite PK).
- IDs are opaque to clients; never expose sequential integers.

## 7. Timestamps

- `created_at timestamptz NOT NULL DEFAULT now()`.
- `updated_at timestamptz NOT NULL DEFAULT now()`, maintained by SQLAlchemy `onupdate=func.now()` **and** a trigger `set_updated_at()` (migration `0002_updated_at_trigger`) so raw updates also bump it.
- Domain timestamps (`completed_at`, `revoked_at`, `archived_at`, ...) nullable; NULL means "not happened".

## 8. Soft deletion

| Table | Strategy |
|---|---|
| users | `deleted_at` + `status='deleted'`; hard-purged by `purge_deleted_users` within 24 h |
| conversations | `deleted_at` (trash); restorable for 30 days; hard-deleted by `purge_trashed_conversations` (daily) |
| files | `deleted_at` + `status='deleted'`; S3 object + chunks deleted by `purge_deleted_files` within 1 h |
| memories | `deleted_at`; hard-deleted after 7 days (allows undo toast) |
| messages, message_parts, document_chunks, tool_calls | no soft delete; removed by cascade from parent |
| api_keys, sessions | `revoked_at` (never reused); rows purged 90 days after revocation/expiry |
| audit_logs, payments, webhook events | never deleted by the app (retention job only) |

Repositories apply `deleted_at IS NULL` by default; explicit `include_deleted=True` for trash views and purges. Partial indexes include `WHERE deleted_at IS NULL`.

## 9. Constraints and foreign keys

- Every FK is indexed (either its own index or leading column of a composite).
- `ON DELETE` rules:
  - Child data of a user (`sessions`, `conversations`, `files`, `memories`, `api_keys`, `user_preferences`, `feedback`, `data_exports`, `usage_daily`) → `CASCADE` from `users`.
  - `messages`, `conversation_files` → `CASCADE` from `conversations`; `message_parts`, `tool_calls` → `CASCADE` from `messages`; `document_chunks` → `CASCADE` from `files`.
  - Financial/audit rows (`payments`, `subscriptions`, `audit_logs`, `usage_records`, `analytics_events`) → `SET NULL` on user deletion (retain anonymized for accounting and aggregate metrics).
- CHECK constraints for enums, non-negative counters, ranges (e.g., `importance BETWEEN 1 AND 5`), and lengths where the DB is the last line of defense (`char_length(title) <= 200`).
- Deferrable FK: `conversations.current_leaf_message_id → messages.id` is `DEFERRABLE INITIALLY DEFERRED`, `ON DELETE SET NULL`, because the conversation and message are inserted in the same transaction.

## 10. Indexing strategy

- Every user-scoped list query has an index `(user_id, <sort column> DESC)` with `WHERE deleted_at IS NULL` when applicable.
- Full-text search: generated `tsvector` columns (`simple` configuration, language-agnostic) + GIN.
- Title fuzzy search: `gin (title gin_trgm_ops)`.
- Vector: HNSW (`vector_cosine_ops`, `m=16`, `ef_construction=64`) on `document_chunks.embedding` and `memories.embedding` (`21_VECTOR_SEARCH.md`).
- JSONB: GIN only where queried (`audit_logs.metadata` is not indexed; `analytics_events.properties` not indexed).
- Create indexes `CONCURRENTLY` in migrations on existing large tables.
- Review `pg_stat_statements` weekly (Phase 11) for missing indexes; no query in the hot path may do a sequential scan on a table > 10k rows.

## 11. pgvector

- Column type `vector(EMBEDDING_DIMENSIONS)`; the dimension is fixed at migration time from `EMBEDDING_DIMENSIONS` (migration reads settings and fails if unset).
- Changing embedding model/dimension requires a re-embedding migration (`21_VECTOR_SEARCH.md` §9). The `embedding_model` column records which model produced each vector; queries filter to the current model.
- `SET LOCAL hnsw.ef_search = 100` inside the retrieval transaction.

## 12. JSONB usage policy

JSONB is allowed for: flexible metadata (`message_parts.data`, `files.metadata`, `audit_logs.metadata`, `plans.limits`, `system_settings.value`, `tool_calls.arguments/result`). JSONB **must not** replace relational columns that are filtered, joined, or constrained. JSONB contents have Pydantic schemas in code (`app/schemas/jsonb/*.py`) and are validated before write.

## 13. Data retention jobs (ARQ cron)

| Job | Schedule (UTC) | Action |
|---|---|---|
| `purge_trashed_conversations` | daily 02:00 | hard-delete conversations with `deleted_at < now() - 30 days` |
| `purge_deleted_users` | hourly | hard-delete users with `status='deleted'`; delete their S3 prefix |
| `purge_deleted_files` | every 10 min | delete S3 objects, rows of files with `status='deleted'` |
| `purge_expired_sessions` | daily 03:00 | delete sessions expired/revoked > 90 days |
| `null_old_ips` | daily 03:30 | set `ip_address=NULL` on sessions/audit_logs older than 180 days |
| `purge_old_analytics` | daily 04:00 | delete `analytics_events` older than 400 days |
| `purge_soft_deleted_memories` | daily 04:30 | hard-delete memories deleted > 7 days |
| `expire_data_exports` | hourly | delete export objects past `expires_at` |
