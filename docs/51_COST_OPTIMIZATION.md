# 51 — Cost Optimization

## 1. Cost model

| Cost center | Driver | Measured by |
|---|---|---|
| Groq inference | tokens × model price | `usage_records.estimated_cost_usd_micros` (per request/user/model) |
| Compute (api, worker, TEI, sandbox, web functions) | instance-hours, Vercel function GB-s | cloud billing + tags (`service`, `env`) |
| Database | instance size, storage, IOPS, backups | cloud billing |
| Redis | node size | cloud billing |
| Object storage & bandwidth | GB-month, requests, egress | cloud billing, S3 Storage Lens |
| Monitoring | log/metric/trace ingest volume | vendor billing |
| Search provider (if paid) | queries | `usage_records` kind `web_search` |
| Payments | Razorpay fees (% of revenue) | payments table |

A monthly **unit economics report** (script `scripts/cost_report.py`, admin-run) computes: cost per active user, cost per message, Groq cost per plan, gross margin per plan = (plan revenue − attributed Groq cost − allocated infra) / revenue. Infra is allocated per active user.

## 2. Groq usage controls

1. **Right-size models:** internal purposes (titles, summaries, memory extraction, query rewrites) use the `fast` model (`15` §2).
2. **Budgeted context:** `16_CONTEXT_MANAGEMENT.md` budgets; summaries replace long histories; RAG top-K capped; tool results truncated.
3. **Output caps:** plan `max_output_tokens`; default output tokens per model conservative (1–2k).
4. **Avoid wasted calls:** memory extraction pre-filter (most turns skip), title generation once, query rewrite only for follow-ups, summaries only above thresholds.
5. **Caching:** embeddings, search results; identical title requests never repeated.
6. **Quotas:** plan quotas + global daily token budget (`35` §7).
7. **Stop early:** cancellation closes the upstream stream immediately (no paying for unseen tokens).
8. **Eval cost caps:** `EVAL_MAX_COST_USD`.
9. **Monitoring:** daily cost anomaly alert (> 120% of 7-day average), top-users-by-cost table; abuse flags.
10. Staging uses a separate Groq key with a spend limit; CI uses the stub by default.

## 3. Database

- Start with Graviton instances (`m6g`) and gp3 storage; scale vertically only on sustained CPU > 60%.
- Keep hot tables lean: large payloads (tool results ≤ 256 KB, extracted text) — extracted full text stored in S3 (`derived/text.txt`), not in DB.
- Partition and drop old analytics/usage partitions instead of bulk deletes.
- Purge jobs keep trash/deleted data from accumulating.
- Read replica added only at S3 stage.
- Reserved instances / savings plans after 3 months of stable usage.

## 4. Storage & bandwidth

- Lifecycle rules (`50` §3); exports expire in 2 days; orphan uploads purged; derived images compressed (WEBP).
- Direct-to-S3 uploads/downloads (no API egress double-counting).
- S3 Intelligent-Tiering for `users/*/files/*` objects > 128 KB after 30 days.
- Per-plan storage quotas.
- CDN (CloudFront) for image thumbnails at S4 to reduce S3 request costs.
- Keep traffic intra-region (Mumbai) to avoid cross-region transfer, except DR replication.

## 5. Workers & auxiliary services

- Autoscale workers on queue depth down to 1 task; `files_low` reprocessing runs off-peak.
- TEI on CPU until embedding latency or throughput requires GPU; batch embeddings.
- Sandbox ASG scales to 1 instance off-peak; per-execution limits bound cost; per-plan daily limits.
- SearXNG self-hosted to avoid per-query fees; Brave only if quality requires it.
- ClamAV sized minimally; signature DB updates cached.

## 6. Web (Vercel)

- The BFF proxy streams SSE, consuming function duration; mitigate by: `maxDuration=300` cap with resume; coalesced deltas (fewer writes); static marketing pages (ISR) cost nothing per request. If proxy duration costs dominate at S3+, move the web app to self-hosted Next.js containers on ECS behind the same ALB (ADR) — no code changes needed.

## 7. Monitoring costs

- Trace sampling 10% (+ errors); metrics cardinality limits (no user ids in metric labels); logs at INFO with health checks sampled at 1%; log retention 30 days hot.
- Sentry: ignore expected 4xx; rate-limit events; release health sampling.

## 8. Cost per user and per request

- Per request: `usage_records.estimated_cost_usd_micros` (Groq) + amortized infra per request (monthly infra / requests), shown in admin usage.
- Per user: sum of Groq cost + allocated infra; admin "Top users by cost" + alerts for users exceeding 3× plan revenue in Groq cost in a month (review plan limits).

## 9. Review cadence

Monthly FinOps review: unit economics report, anomalies, rightsizing recommendations (AWS Compute Optimizer), Groq model price changes (update registry pricing), plan limit adjustments (business decision).
