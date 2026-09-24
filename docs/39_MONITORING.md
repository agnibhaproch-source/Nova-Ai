# 39 — Monitoring & Observability

## 1. Stack

- **Traces & metrics:** OpenTelemetry SDKs in api, worker, sandbox-runner, and Next.js server (`@vercel/otel` or `@opentelemetry/sdk-node`) → OTLP (`OTEL_EXPORTER_OTLP_ENDPOINT`) → reference backend Grafana Cloud (Tempo + Prometheus/Mimir + Loki) or any OTLP-compatible backend.
- **Errors:** Sentry (web client, web server, api, worker).
- **Logs:** JSON stdout (`38_LOGGING.md`).
- **Uptime:** external synthetic checks (reference: Grafana Synthetic Monitoring or Better Stack) on `https://APP_URL/`, `https://APP_URL/api/v1/app-config`, `/readyz` via proxy, every 1 min from 3 regions.
- **Dashboards as code:** `infra/observability/dashboards/*.json` and alert rules `infra/observability/alerts/*.yaml` (Phase 11).

## 2. Instrumentation

| Component | Auto-instrumentation | Manual spans |
|---|---|---|
| FastAPI | `opentelemetry-instrumentation-fastapi` (exclude `/healthz`) | `chat.generate`, `context.build`, `rag.retrieve`, `groq.chat`, `tool.<name>`, `quota.check` |
| SQLAlchemy | `opentelemetry-instrumentation-sqlalchemy` (no statement params) | — |
| Redis | `opentelemetry-instrumentation-redis` | — |
| httpx | `opentelemetry-instrumentation-httpx` | — |
| ARQ jobs | manual wrapper: span `job.<name>` linked to enqueueing trace via `traceparent` in job kwargs | stage spans in document pipeline |
| Next.js | route handler spans; proxy span `proxy.upstream` | — |

Sampling: parent-based; 10% of traces in production (`OTEL_TRACES_SAMPLER=parentbased_traceidratio`, arg 0.1), 100% for errors (tail sampling in the collector keeps traces with error status or latency > 5 s).

## 3. Metrics catalogue (Prometheus naming)

### Traffic & latency
- `http_server_request_duration_seconds{route,method,status}` (OTel semantic convention histogram)
- `nova_sse_active_streams{instance}` (gauge)
- `nova_sse_streams_total{outcome}` (`complete`, `client_disconnect`, `error`, `resumed`)
- `nova_sse_resume_total{result}` (`replayed`, `snapshot`, `interrupted`)
- `nova_chat_ttft_seconds{model_key}` (histogram, server-measured from request start to first delta published)
- `nova_chat_generation_seconds{model_key,status}`
- `nova_stream_degraded_total`

### Groq
- `nova_groq_requests_total{model_key,purpose,status}`
- `nova_groq_errors_total{type}` (`rate_limited`, `timeout`, `unavailable`, `auth`, `bad_request`, `model_unavailable`)
- `nova_groq_latency_seconds{model_key,purpose}`, `nova_groq_ttft_seconds{model_key}`
- `nova_groq_tokens_total{model_key,direction}`
- `nova_groq_circuit_open{groq_model_id}` (gauge 0/1)
- `nova_groq_ratelimit_remaining_tokens{groq_model_id}` (gauge from headers)
- `nova_context_estimate_ratio{model_key}` (histogram actual/estimated prompt tokens)

### Features
- `nova_tool_calls_total{tool,status}`, `nova_tool_latency_seconds{tool}`
- `nova_rag_retrieve_seconds`, `nova_rag_empty_total`, `nova_rag_invalid_citation_total`
- `nova_file_processing_seconds{extension,status}`, `nova_files_in_state{status}` (gauge, polled)
- `nova_memory_ops_total{op}`, `nova_memory_rejected_total{reason}`
- `nova_ratelimit_decisions_total{policy,result}`, `nova_ratelimit_fallback_total`
- `nova_quota_exceeded_total{quota}`
- `nova_billing_webhooks_total{event_type,result}`

### Infrastructure
- DB: `db_client_connections_usage{state}` (pool), `nova_db_query_duration_seconds` (from instrumentation), managed DB metrics (CPU, memory, IOPS, connections, replication lag, storage) via cloud integration.
- Redis: memory, ops/s, evictions, connected clients (cloud integration), app-side `nova_redis_errors_total`.
- Storage: `nova_storage_errors_total{op}`, latency histogram.
- Workers: `nova_jobs_total{job,status}`, `nova_job_duration_seconds{job}`, `nova_queue_depth{queue}` (polled every 15 s), `nova_queue_oldest_job_age_seconds{queue}`, `nova_worker_heartbeat_age_seconds{worker}`.
- Sandbox: `nova_sandbox_executions_total{status}`, `nova_sandbox_active`, `nova_sandbox_orphans_removed_total`.
- Containers: CPU %, memory RSS, restarts, instance count (platform metrics).

## 4. Dashboards

1. **Service overview:** RPS, error rate, p50/p95/p99 latency by route, active SSE streams, instance count, CPU/memory.
2. **Chat & Groq:** TTFT p50/p95 by model, generation duration, Groq error breakdown, circuit states, token throughput, rate-limit headroom, cancellations, failed/interrupted generations.
3. **Files & RAG:** processing duration by type, queue depth, failures by code, retrieval latency, empty-retrieval rate, invalid citations.
4. **Tools:** calls/success rate/latency per tool; sandbox capacity.
5. **Data stores:** DB connections, slow queries, replication lag, Redis memory/latency, storage errors.
6. **Business:** signups, DAU, messages, tokens, est. cost/day, subscriptions (from DB via scheduled metric export job `export_business_metrics` every 5 min).

## 5. Alerts

Severity: **P1** pages on-call (24/7), **P2** pages during business hours, **P3** ticket/Slack.

| Alert | Condition | Severity |
|---|---|---|
| API down | Synthetic check fails 3 consecutive minutes from ≥ 2 regions | P1 |
| High 5xx | 5xx rate > 2% for 5 min (excluding provider-mapped 502/504) | P1 |
| Groq failures | `nova_groq_errors_total` / requests > 10% for 5 min, or circuit open > 5 min | P1 |
| Groq auth error | any `type="auth"` | P1 |
| TTFT degraded | p95 TTFT > 3 s for 15 min | P2 |
| SSE failures | `outcome=error` > 5% of streams for 10 min | P2 |
| DB unhealthy | readiness DB check failing 2 min, CPU > 85% 10 min, connections > 85% of max, replication lag > 30 s | P1/P2 |
| Redis unhealthy | unreachable 1 min (P1); memory > 85% (P2); evictions > 0 for 10 min (P2) | P1/P2 |
| Storage errors | error rate > 5% for 5 min | P2 |
| Queue backlog | `files` oldest job age > 10 min, or any queue depth > 1,000 | P2 |
| Worker heartbeat | no heartbeat from any worker for 2 min | P1 |
| Stale generations | reaper marked > 20 messages interrupted in 10 min | P2 |
| Sandbox | runner health failing 3 min; orphan removals > 10/h | P2 |
| Account purge overdue | any deleted user not purged after 24 h | P2 |
| Webhook failures | any Razorpay webhook processing error unresolved for 30 min | P2 |
| Cost | daily estimated Groq cost > 120% of 7-day average, or global budget 90% | P2 |
| Rate-limit fallback active | > 0 for 5 min | P2 |
| Error budget burn | 99.9% SLO: 14.4× burn over 1 h (P1), 6× over 6 h (P2) | P1/P2 |
| Certificate expiry | < 14 days | P3 |
| Dependency vulnerabilities | new critical in production image | P3 |

Alert routing: PagerDuty/Opsgenie (reference) for P1/P2; Slack `#nova-alerts` for all. Each alert links to a runbook `docs/runbooks/<alert>.md` (created in Phase 11).

## 6. SLOs

| SLI | SLO |
|---|---|
| Availability: successful (non-5xx, excluding provider 502/504) API responses | 99.9% / 30 days |
| Chat success: assistant messages completed or user-cancelled / all generations (excluding provider outages declared) | 99.0% |
| TTFT p95 (server-measured) | ≤ 2 s |
| File processing success (non-user-error) | 99% |

## 7. Sentry configuration

- `dsn` from `SENTRY_DSN` (api/worker) and `NEXT_PUBLIC_SENTRY_DSN` (web).
- `environment=APP_ENV`, `release=<version>` (source maps uploaded in CI for web, then deleted from the deploy artifact).
- `traces_sample_rate=0` (tracing via OTel), `send_default_pii=False`, `before_send` scrubbing (`33_SECURITY.md` §14), tags: `request_id`, `route`, `user_id` (UUID only).
- Ignore expected errors (`AppError` with status < 500).

## 8. Health endpoints

- `/healthz` — liveness: process up (no dependency checks).
- `/readyz` — readiness: DB `SELECT 1` (timeout 1 s), Redis `PING` (500 ms), migration head match; storage/Groq reported but non-fatal. Used by load balancer target health (interval 10 s, unhealthy after 3 failures).
- Worker: heartbeat key every 15 s; container health command `python -m app.workers.healthcheck` checks heartbeat freshness.
