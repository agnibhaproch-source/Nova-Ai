# 49 — Scalability

The architecture is designed so each growth stage needs **configuration and capacity changes, not rewrites**. Assumptions per registered user: ~30% weekly active, ~10 messages/active day, ~5 files stored, peak concurrency ≈ 5% of DAU streaming simultaneously.

## 1. Stage table

| Stage | Registered users | Peak concurrent streams | Topology | Key actions |
|---|---|---|---|---|
| S0 | 10 | < 5 | Single small environment (1 api, 1 worker, smallest managed DB/Redis) or even a single VM with Compose for internal alpha | Correctness, observability baseline |
| S1 | 100 | ~10 | 2 api tasks (HA), 1 worker, db.t4g.medium, cache.t4g.small | Alerts, backups verified, rate limits tuned |
| S2 | 1,000 | ~50 | 2–3 api, 1–2 workers, db.m6g.large Multi-AZ, Redis with replica, TEI 1 task | **PgBouncer** (RDS Proxy or PgBouncer sidecar) in transaction mode; `pg_stat_statements` reviews; CDN for static; Groq limit increase request |
| S3 | 10,000 | ~300 | 3–6 api (autoscaling), 2–6 workers, db.m6g.xlarge + read replica, Redis m6g.large, TEI 2–3 tasks | Monthly **partitioning** of `usage_records`, `analytics_events`, `audit_logs`; admin/analytics queries on replica; embeddings batching tuned; HNSW `ef_search` tuning; sandbox ASG 2–4 |
| S4 | 100,000+ | ~3,000 | 10–40 api, 6–20 workers, db.r6g.2xlarge+ (vertical) + 2 replicas, Redis cluster mode or separate clusters per function, TEI GPU | Split Redis by role (rate-limit/cache vs streams vs queues); hash-partition `document_chunks` & `messages` by `user_id`; archive cold conversations; consider dedicated SSE gateway; multi-region read (future) |

## 2. Stateless API and horizontal scaling

- No in-process state that matters across requests: sessions (DB + Redis cache), rate limits (Redis), streams (Redis Streams), uploads (S3), jobs (Redis queues).
- Autoscaling on CPU and active SSE streams per task. SSE is I/O-bound; each stream costs one coroutine + one Redis `XREAD BLOCK` connection → **Redis connection pooling** via `redis.asyncio.BlockingConnectionPool(max_connections=500)` per process; at S4, streams use a shared per-process multiplexer: one `XREAD` over many stream keys, fanning out to subscribers (implemented behind `GenerationBroker` interface from the start, simple mode first).
- Generation tasks are bound to the accepting instance; scale-in uses graceful drain.

## 3. Queues

- Separate ARQ queues isolate workloads (`files`, `files_low`, `default`, `exports`, `cron`) so a document flood cannot delay titles/memory.
- Worker autoscaling on queue depth/age; per-queue concurrency limits.
- Idempotent jobs + retry allow scaling in/out safely.

## 4. Database

- **Indexes:** every hot query has a composite index starting with `user_id`/parent FK (SCL-003); verified by `EXPLAIN` tests on seeded large datasets (`tests/perf/explain_test.py` asserts index usage for 12 core queries with 1M messages).
- **Connection pooling:** app pools + PgBouncer/RDS Proxy at S2+.
- **Read replicas** for admin dashboards, analytics, exports (S3+). User-facing reads stay on primary (read-your-writes).
- **Partitioning** (S3+): `usage_records`, `analytics_events`, `audit_logs` → `PARTITION BY RANGE (created_at)` monthly; partitions created 3 months ahead by cron job `ensure_partitions`; old partitions detached/dropped by retention jobs (cheap deletes).
- **Large tables** (S4): `messages`, `message_parts`, `document_chunks` → `PARTITION BY HASH (user_id)` into 16–64 partitions via expand/contract migration (new partitioned tables + dual write + backfill + swap). Vector indexes per partition reduce HNSW sizes and improve filtered search.
- **Vacuum/autovacuum** tuned for high-churn tables (`messages` checkpoints update rows during streaming → `fillfactor=90` on `messages` and `message_parts` for HOT updates).
- Write amplification control: streaming checkpoints ≤ 1/s per active generation → at 3,000 concurrent streams ≈ 3,000 small updates/s (fits a well-sized primary); if needed, raise checkpoint interval to 2 s.

## 5. Caching

| Cache | Benefit |
|---|---|
| Session lookup (60 s) | Removes a DB query per request |
| Preferences / system prompt / memories list (5 min) | Faster context build |
| Query embeddings (24 h) | Fewer embedding calls |
| Web search results (1 h) & pages (6 h) | Provider cost & latency |
| Model registry health (10 min) | Avoid Groq model list calls |
| Plans/settings (30–60 s) | Avoid DB reads |
| Admin analytics (10 min) | Heavy aggregates |

Cache stampede protection: `SET NX` rebuild locks + jittered TTLs.

## 6. Object storage

S3 scales transparently; direct browser uploads/downloads via presigned URLs keep file bytes off API servers. At S4, serve image thumbnails through CloudFront with signed URLs (short TTL) to reduce S3 GET costs and latency.

## 7. Rate limiting and fairness

Per-user/plan limits prevent single users from exhausting shared capacity (Groq account limits are a shared resource). At S3+, a **global Groq concurrency governor** (Redis semaphore per `groq_model_id`, sized to Groq account limits) queues requests fairly (FIFO with plan priority: pro > plus > free, max queue wait 5 s) before returning `PROVIDER_RATE_LIMITED`.

## 8. Groq capacity

Groq account rate limits (RPM/TPM per model) are the most likely bottleneck. Actions by stage: S1 monitor headroom; S2 request limit increases; S3 route internal purposes (titles, summaries, extraction) to the `fast` model and defer non-urgent jobs (memory extraction, summaries) when headroom < 20%; S4 negotiate enterprise capacity with Groq. Still Groq-only.

## 9. Embeddings & RAG

TEI scales horizontally; batch size tuned; GPU instances at S4. Document processing throughput scales with workers + TEI. Retrieval uses exact search for small scopes (fast regardless of total size) and filtered HNSW for large scopes (`21` §5.1).

## 10. Frontend

Static assets on Vercel CDN; route-level code splitting; lazy Shiki/KaTeX; virtualized lists; SSE avoids polling. Scale is handled by Vercel; the BFF proxy's function duration is the main cost driver (see `51_COST_OPTIMIZATION.md` §6).

## 11. Load testing gates per stage

Before declaring readiness for the next stage, k6 must demonstrate 2× the stage's expected peak concurrent streams with TTFT p95 within NFR-001 (using the Groq stub for capacity of our own system) and a real-Groq run at expected peak for end-to-end validation.
