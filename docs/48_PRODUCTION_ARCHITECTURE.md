# 48 — Production Architecture

## 1. Topology

```
                         Users (browsers, API clients)
                                   │ HTTPS
                     ┌─────────────▼──────────────┐
                     │ Vercel Edge + Next.js (bom1)│  static assets, SSR, BFF proxy (/api/v1/*)
                     └─────────────┬──────────────┘
                                   │ HTTPS + X-Nova-Proxy-Secret
                     ┌─────────────▼──────────────┐
                     │ AWS WAF → ALB (multi-AZ)   │  TLS, idle timeout 350s, health /readyz
                     └──────┬───────────────┬─────┘
                            │               │
            ┌───────────────▼──┐     ┌──────▼───────────┐
            │ api task (AZ-a)  │ ... │ api task (AZ-c)  │   stateless; SSE; generation tasks
            └──┬─────┬─────┬───┘     └──┬─────┬────┬────┘
               │     │     │            │     │    │
   ┌───────────▼┐ ┌──▼─────▼───────┐ ┌──▼─────▼────▼──────────┐
   │ RDS PG16   │ │ ElastiCache    │ │ S3 (versioned, SSE)    │
   │ Multi-AZ   │ │ Redis primary  │ └────────────────────────┘
   │ (+replica) │ │ + replica      │
   └─────▲──────┘ └──────▲─────────┘
         │               │ ARQ queues / streams
   ┌─────┴───────────────┴─────┐     ┌──────────────────┐   ┌──────────────────────────┐
   │ worker tasks (1..6)       │────►│ embeddings (TEI) │   │ sandbox-runner ASG       │
   │ files, memory, summaries, │     └──────────────────┘   │ (isolated subnet, gVisor)│
   │ exports, purges, cron     │────► clamav, searxng       └──────────▲───────────────┘
   └───────────────────────────┘                                       │ api → runner (8090)
         Egress (NAT): Groq API, Razorpay API, SES, Brave (if used), web pages via SafeFetcher
Observability: OTel collector (sidecar/daemon) → Grafana Cloud; Sentry; CloudWatch logs
```

## 2. Load balancing

- ALB round-robin (least outstanding requests algorithm) across api tasks in 3 AZs.
- No sticky sessions required: sessions in DB/Redis; SSE resumption works across instances via Redis Streams.
- Connection draining 35 s; app-level SIGTERM handling finishes/hands off streams (`13` §4).
- Vercel handles global edge caching for static assets only; API responses are `no-store`.

## 3. API instances

- Stateless; any instance can serve any request.
- Per instance: 2 gunicorn workers × async event loop; ≥ 500 concurrent SSE connections per instance (SCL-005).
- Generation tasks run on the instance that accepted the POST; if the instance dies, the reaper marks the message `failed` (`GENERATION_INTERRUPTED`) within 2 min and the client offers Retry.

## 4. Workers

- ARQ workers consume queues: `default` (titles, memory, summaries, email), `files`, `files_low`, `exports`, `cron` (single-leader cron via ARQ's built-in unique job ids + Redis lock).
- Heartbeats in Redis; jobs idempotent; retries with backoff; dead jobs visible in admin health.

## 5. Data stores

- **PostgreSQL:** Multi-AZ synchronous standby, automatic failover (~60–120 s). Connection strings use the cluster endpoint; the app retries idempotent reads once on `ConnectionError` and surfaces `DATABASE_ERROR` (503, retryable) otherwise.
- **Redis:** primary + replica with automatic failover. Loss of Redis data is tolerable (rate limits reset, streams lost → snapshots via DB, queues: jobs lost are recovered by reconciliation cron `requeue_stuck_files` which re-enqueues files in `uploaded/processing` with `updated_at` older than 15 min).
- **S3:** 11 nines durability; versioning + lifecycle.

## 6. Monitoring

Per `39_MONITORING.md`: OTel collector sidecar in each ECS task (or ADOT daemon), Sentry, synthetic checks, alerts routed to on-call.

## 7. Failure scenarios and recovery

| # | Failure | Impact | Detection | Automatic response | Manual recovery |
|---|---|---|---|---|---|
| F1 | One api task crashes | In-flight generations on it interrupted | ECS health, reaper metrics | ECS replaces task; clients resume → `GENERATION_INTERRUPTED` → Retry | None |
| F2 | AZ outage | Reduced capacity | ALB/ECS metrics | ECS reschedules in other AZs; RDS/Redis fail over | Monitor; scale max |
| F3 | Groq outage / elevated errors | Chat unavailable/degraded | Groq error alerts, circuit breaker | Circuit opens; fallback model if configured; users see `PROVIDER_UNAVAILABLE` banner; other features work | Status page update; nothing else possible (single provider by design) |
| F4 | Groq rate limit exhaustion | 429s | `nova_groq_errors_total{type=rate_limited}` | Backoff, queued throttling, fallback model | Request higher Groq limits; enable global budget / lower free plan limits |
| F5 | RDS primary failure | 1–2 min write unavailability | Readiness fails, alerts | Multi-AZ failover; readiness returns; requests retried by clients | Verify replication; post-incident review |
| F6 | RDS data corruption / bad migration | Data risk | Alerts, user reports | — | PITR restore to new instance (`50` §5), repoint, replay if possible |
| F7 | Redis failover | Seconds of errors | Redis alerts | Client reconnect; degraded modes (`34` §7, `13` §12) | None |
| F8 | Redis total loss | Rate limits/quotas reset, streams lost, queued jobs lost | Alerts | Counters rebuilt from DB; resume uses snapshots; reconciliation cron re-enqueues files | Restore cluster; verify queues |
| F9 | S3 regional issue | Uploads/downloads fail | Storage error alerts | `STORAGE_ERROR` shown; chat without files continues | Wait/failover per AWS; (future) cross-region replication |
| F10 | Worker backlog | Slow file processing | Queue age alert | Autoscale workers | Investigate stuck jobs; scale embeddings |
| F11 | Embeddings service down | Uploads stall in processing; RAG query embedding fails | Health/alerts | Jobs retry; RAG falls back to FTS-only retrieval (flag `rag.degraded`) | Restart/scale TEI |
| F12 | Sandbox runner down | Code tool unavailable | Health alert | Tool marked unavailable in `GET /tools` (health cached 30 s); model told tool unavailable | Replace instances |
| F13 | Bad deploy | Errors spike | Smoke/5xx alerts | Automatic rollback | Fix forward |
| F14 | Secret leak | Security incident | gitleaks/reports | — | Rotate, revoke, audit (`33` §18) |
| F15 | Razorpay webhook outage | Plan activation delayed | Webhook alert | Client-side verify path still activates; reconciliation job `sync_subscriptions` (hourly) fetches live status for non-terminal subscriptions | None |
| F16 | Email provider failure | Password-reset emails delayed | Job failures | Email job retries 5× over 1 h | Switch SMTP provider via env |
| F17 | Region-wide AWS outage | Full outage of API | Synthetic checks | — | DR procedure (`50` §6) |

## 8. Capacity headroom policy

Maintain ≥ 40% headroom on api CPU/connection capacity at daily peak; DB CPU p95 < 60%; Redis memory < 70%; worker queue age p95 < 2 min. Review monthly.
