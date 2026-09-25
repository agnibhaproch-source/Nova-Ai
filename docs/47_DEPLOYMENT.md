# 47 — Deployment

## 1. Reference deployment

The architecture is cloud-portable; the **reference** target (used for runbooks and IaC) is:

| Component | Reference service | Requirement (if substituting) |
|---|---|---|
| Web (Next.js) | **Vercel** (Pro), region `bom1` (Mumbai) | Node runtime route handlers with streaming responses ≥ 300 s |
| API + worker | **AWS ECS on Fargate**, region `ap-south-1` (Mumbai), behind an **Application Load Balancer** | Managed containers, rolling deploys, long-lived HTTP (idle timeout ≥ 300 s), autoscaling |
| Sandbox runner | **EC2** (dedicated ASG, Linux with gVisor `runsc` installed) in a private isolated subnet | VM-level isolation; Docker + gVisor |
| Embeddings (TEI) | ECS service (CPU; GPU optional later) in private subnet | Internal HTTP |
| PostgreSQL | **Amazon RDS for PostgreSQL 16** Multi-AZ with pgvector | Managed, pgvector ≥ 0.7, PITR |
| Redis | **Amazon ElastiCache for Redis 7** (cluster mode disabled, Multi-AZ replica, TLS + AUTH) | Managed or reliably hosted; persistence not required for correctness |
| Object storage | **Amazon S3** (versioning on, SSE-S3, Block Public Access) | S3-compatible, durable |
| Email | Amazon SES (SMTP interface) | SMTP |
| Search | SearXNG on ECS (private) or Brave API | — |
| ClamAV | ECS service (private) | — |
| Secrets | AWS Secrets Manager + ECS task secrets; Vercel env (encrypted) | — |
| DNS/TLS | Route 53 + ACM (ALB), Vercel-managed TLS for web | TLS 1.2+ |
| Observability | Grafana Cloud (OTLP), Sentry SaaS | OTLP-compatible |

Alternatives that meet the requirements (Render, Fly.io, Google Cloud Run + Cloud SQL + Memorystore + GCS, Railway for early stages) are acceptable via ADR; the application code does not change.

## 1b. Single-server option (implemented)

`infra/deploy/`: one Linux host running Caddy (automatic HTTPS; `files.<domain>` → RustFS (S3-compatible) for presigned uploads) → web → API, plus worker, Postgres (pgvector), Redis, RustFS storage; optional sandbox runner on gVisor. `.github/workflows/deploy.yml` builds the four images to GHCR (tag `sha-…`), copies the compose files over SSH, pulls, migrates (one-off `migrate` service before the API starts) and smoke-tests. Rollback = previous `IMAGE_TAG`. Backups: `infra/deploy/backup.sh` (pg_dump + object mirror, ship off-host). See `infra/deploy/README.md`.

## 2. Environments

| Env | Web | API | Data | Groq key |
|---|---|---|---|---|
| development | local | local | local containers | developer's key |
| test (CI) | compose | compose | ephemeral | stub (+ low-quota key for evals) |
| staging | `staging.<domain>` (Vercel) | ECS `nova-staging` | separate RDS/Redis/S3 (smaller) | staging key with spend limit |
| production | `<domain>` (Vercel) | ECS `nova-prod` | production RDS/Redis/S3 | production key |

Staging mirrors production topology at reduced size; production data is never copied to staging.

## 3. Network layout (AWS)

```
VPC 10.20.0.0/16 (ap-south-1, 3 AZs)
 ├─ public subnets:   ALB, NAT gateways
 ├─ private-app:      ECS api, worker, embeddings, searxng, clamav
 ├─ private-data:     RDS, ElastiCache (SG: only from private-app)
 └─ isolated-sandbox: sandbox-runner EC2 (SG inbound: only api/worker SG on 8090; outbound: VPC endpoints for ECR/CloudWatch only; NO NAT route)
```

- ALB listener 443 → target group `api` (HTTP 8000); health check `/readyz` (proxy-secret exempt from internal health checker by source SG + path); idle timeout 350 s.
- The API is reachable only from Vercel: ALB SG allows 443 from anywhere (Vercel egress IPs are not static), **plus** every request must carry `X-Nova-Proxy-Secret` (§05 §3); optionally add AWS WAF rule requiring the header (defense in depth) and rate-based rules.
- S3 accessed via VPC gateway endpoint from private subnets; browsers use presigned URLs to `https://<bucket>.s3.ap-south-1.amazonaws.com`.

## 4. Web (Vercel) configuration

- Project root `apps/web`; build `pnpm build`; framework preset Next.js; region `bom1`.
- Env (server): `API_INTERNAL_URL=https://api.<domain>` (ALB), `API_PROXY_SHARED_SECRET`, `APP_URL`, `S3_PUBLIC_ENDPOINT`, `APP_ENV`, observability vars. Env (public): §42 §12.
- Route handler `app/api/v1/[...path]/route.ts`: `maxDuration = 300` (Vercel plan must allow it).
- Vercel does not buffer streamed route handler responses; verify with the E2E streaming test against staging after each Vercel config change.

## 5. Release process (per `46_CI_CD.md` §5)

1. Images built once per commit, pushed to ECR with immutable `sha-<short>` tags.
2. **Migrations** run as a one-off ECS task (`alembic upgrade head`, role `nova_migrator`) before service updates. Failure aborts the deploy.
3. ECS services updated: `api` (rolling, min healthy 100%, max 200%, deregistration delay 35 s to let SSE drain), `worker` (rolling; ARQ graceful shutdown finishes current jobs up to 5 min, `stopTimeout=120` s, remaining jobs retried), `sandbox-runner` (ASG instance refresh, min healthy 50%).
4. Vercel production deployment promoted after API is healthy (web is backward compatible with the previous API version by contract rules).
5. Smoke tests; automatic rollback on failure.

## 6. Service sizing (initial production)

| Service | Task size | Count (min/max) | Autoscaling signal |
|---|---|---|---|
| api | 1 vCPU / 2 GB, `WEB_CONCURRENCY=2` | 2 / 10 | CPU > 60%, or `nova_sse_active_streams` per task > 300 |
| worker | 1 vCPU / 3 GB (`WORKER_MAX_JOBS=8`, 2 extract processes) | 1 / 6 | queue depth (`files` > 50) via CloudWatch custom metric |
| embeddings | 2 vCPU / 4 GB | 1 / 3 | CPU > 70% |
| sandbox-runner | c6i.large (2 vCPU / 4 GB) | 1 / 4 | active executions > 70% of capacity |
| searxng | 0.5 vCPU / 1 GB | 1 / 2 | CPU |
| clamav | 1 vCPU / 3 GB | 1 / 2 | — |
| RDS | db.m6g.large Multi-AZ, gp3 100 GB autoscaling | — | — |
| ElastiCache | cache.m6g.large primary + replica | — | — |

## 7. Configuration & secrets

- ECS task definitions reference Secrets Manager ARNs for secret env vars; non-secrets as plain env.
- `models.yaml` is baked into the image; per-environment Groq model IDs come from env vars.
- IAM: api/worker task role → S3 bucket prefix `users/*` read/write, SES send, Secrets Manager read of own secrets; no wildcard `*` actions. Sandbox runner role: ECR pull + logs only.

## 8. Rollback

- Application: redeploy previous task definition revision (`make rollback env=production` wraps `aws ecs update-service --task-definition <prev>`); Vercel "Instant Rollback" to previous deployment.
- Database: migrations are backward compatible, so app rollback does not require DB rollback. Destructive (contract) migrations ship only after the previous release no longer needs the column. Emergency DB restore follows `50_BACKUP_AND_RECOVERY.md`.

## 9. One-time setup runbooks (Phase 1 / Phase 10)

1. Domain + DNS + ACM certificates.
2. RDS: create DB `nova`, roles `nova_migrator` (owner) and `nova_app` (grants per `07` §1), enable `pg_stat_statements`; extensions created by migration `0001` (requires the migrator to have rights to create extensions on RDS: `rds_superuser` for `nova_migrator` or pre-create extensions as master user).
3. S3 bucket with versioning, lifecycle rules (`50` §3), CORS (`18` §5), Block Public Access.
4. SES domain verification (DKIM, SPF, DMARC).
5. Groq: production API key, spend alerts in Groq console, record model IDs in env.
6. (Removed: Razorpay setup; there is no billing, ADR 0004.)
7. Sentry projects (web, api), Grafana Cloud stack, alert routing.
8. Bootstrap admin via `ADMIN_BOOTSTRAP_EMAIL`, then unset it.

## 10. Infrastructure as code

Terraform in `infra/terraform/` (implemented): modules `network`, `rds`, `redis`, `s3`, `ecs_service`, `sandbox_asg`, `observability`, composed in `envs/production`. State in S3 + DynamoDB lock (`backend.hcl`). `make tf-validate` checks formatting and validity without AWS credentials (Terraform 1.16, AWS provider 6.x). Usage and the deploy sequence (push images → run the `migrate` task → apply with the new tag) are in `infra/terraform/README.md`. It has not been applied to a real AWS account yet.
