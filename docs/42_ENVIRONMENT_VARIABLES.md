# 42 — Environment Variables

## 1. Classification

| Class | Meaning | Where |
|---|---|---|
| **server-only** | Secret or internal; must never reach the browser | api, worker, sandbox-runner, Next.js server runtime |
| **public** | Safe for the browser; must be prefixed `NEXT_PUBLIC_` | inlined into web bundle at **build time** |
| **build-time** | Needed during `next build` / image build | CI |

Rules:
- Only variables listed as public may use the `NEXT_PUBLIC_` prefix. CI (`scripts/check_bundle_secrets.sh`) fails if any other secret pattern appears in `.next/static`.
- Backend settings are loaded by `app/core/config.py` (`pydantic-settings`, `env_file=".env"` only in development/test). Unknown `NOVA_*`/listed variables are validated at startup; invalid → process exits with `startup.config_invalid` (critical) naming the variable (never its value).
- Web env validated by `apps/web/src/lib/env.ts` (zod) at build and server start.
- Secrets in deployed environments come from the secret manager; non-secret config from platform env settings.

Column "Svc": `A` api, `W` worker, `R` sandbox-runner, `N` Next.js server, `B` browser (public), `CI` build.

## 2. Core application

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `APP_ENV` | server-only | A W R N | yes | `development` | `development` \| `test` \| `staging` \| `production`; drives validation strictness |
| `APP_URL` | server-only | A W N | yes | `http://localhost:3000` | Public origin (Origin checks, email links, CORS for S3) |
| `APP_VERSION` | build-time | A W N CI | no | `dev` | Injected by CI (`<semver>+sha.<short>`) |
| `LOG_LEVEL` | server-only | A W R N | no | `info` | |
| `LOG_FORMAT` | server-only | A W R | no | `json` | `json` \| `console` (dev only) |
| `API_INTERNAL_URL` | server-only | N | yes | `http://api:8000` | Where the Next.js proxy/SSR reach FastAPI |
| `API_PROXY_SHARED_SECRET` | server-only (secret) | A N | yes | — | ≥ 32 random bytes; header `X-Nova-Proxy-Secret` |
| `AUTH_SECRET` | server-only (secret) | A W | yes | — | ≥ 32 random bytes (base64); HMAC for CSRF, API key hashes, cursors, Groq user hash |
| `AUTH_SECRET_PREVIOUS` | server-only (secret) | A W | no | — | Rotation window support |
| `COOKIE_DOMAIN` | server-only | A | no | — | Omit to use host-only cookies |
| `SESSION_TTL_DAYS` | server-only | A | no | `30` | Absolute session lifetime |
| `SESSION_IDLE_TIMEOUT_DAYS` | server-only | A | no | `7` | Idle timeout (admins fixed 12 h) |
| `ADMIN_BOOTSTRAP_EMAIL` | server-only | A | no | — | First signup with this email becomes admin if no admin exists |
| `WEB_CONCURRENCY` | server-only | A | no | `2` | Gunicorn workers per api container |
| `WORKER_MAX_JOBS` | server-only | W | no | `8` | ARQ concurrency |
| `WORKER_EXTRACT_PROCESSES` | server-only | W | no | `2` | Extraction process pool size |
| `RATE_LIMIT_FALLBACK_DIVISOR` | server-only | A | no | `4` | In-memory fallback limiter divisor |

## 3. Database & Redis

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `DATABASE_URL` | server-only (secret) | A W | yes | `postgresql+asyncpg://nova:nova@postgres:5432/nova` | App role connection |
| `DATABASE_MIGRATOR_URL` | server-only (secret) | release job | prod: yes | = `DATABASE_URL` in dev | Owner role for Alembic |
| `DATABASE_READ_REPLICA_URL` | server-only (secret) | A | no | — | Admin analytics queries (Phase 11) |
| `DATABASE_POOL_SIZE` | server-only | A W | no | `10` (W: `5`) | |
| `DATABASE_MAX_OVERFLOW` | server-only | A W | no | `5` | |
| `DATABASE_POOL_TIMEOUT` | server-only | A W | no | `10` | seconds |
| `DATABASE_USE_PGBOUNCER` | server-only | A W | no | `false` | Disables asyncpg statement caches |
| `REDIS_URL` | server-only (secret) | A W | yes | `redis://redis:6379/0` | `rediss://` with auth in prod |

## 4. Groq (sole LLM provider)

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `DESKTOP_MAC_DOWNLOAD_URL` | server-only (web) | W | no | — | Where `/download/mac` sends users (release/CDN URL); unset = `public/downloads/Nova-mac.dmg` from `make desktop-release` |
| `RATE_LIMIT_GLOBAL_IP_PER_MIN` | server-only | A | no | `300` | Per-IP ceiling across all endpoints; raise only in load-test environments |
| `GROQ_KEY_MODE` | server-only | A W | no | `user` | `user` = each chat uses the key its owner enters (BYOK, docs/14 §2a); `server` = one server key |
| `GROQ_USER_KEY_TTL_HOURS` | server-only | A W | no | `720` | Sliding lifetime of a chat's encrypted key in Redis (30 days; each use extends it, so saved chats keep working) |
| `GROQ_API_KEY` | server-only (secret) | A W | only when `GROQ_KEY_MODE=server` | — | Server-held Groq API key. Never in web |
| `GROQ_DEFAULT_MODEL` | server-only | A W | no | `openai/gpt-oss-120b` | `groq_model_id` for registry key `primary` (facts in `models.yaml` verified from Groq docs; update them together) |
| `GROQ_FAST_MODEL` | server-only | A W | yes | — (set from Groq docs) | For key `fast` (titles, summaries, extraction) |
| `GROQ_VISION_MODEL` | server-only | A W | no | — | Enables key `vision` when set |
| `GROQ_STT_MODEL` | server-only | A | no | — | Enables voice input |
| `GROQ_TTS_MODEL` | server-only | A | no | — | Enables Groq TTS |
| `GROQ_TTS_VOICES` | server-only | A | if TTS | — | Comma-separated voice ids from Groq docs |
| `GROQ_TTS_DEFAULT_VOICE` | server-only | A | if TTS | — | Must be in `GROQ_TTS_VOICES` |
| `GROQ_TIMEOUT_SECONDS` | server-only | A W | no | `60` | Non-stream read timeout |
| `GROQ_MAX_RETRIES` | server-only | A W | no | `2` | Retries before first token |
| `GROQ_MAX_CONCURRENCY_PER_PROCESS` | server-only | A W | no | `64` | Semaphore |
| `GROQ_BASE_URL` | server-only | A W | no | — | **Test only**; rejected in staging/production |
| `MODEL_REGISTRY_PATH` | server-only | A W | no | `config/models.yaml` | Registry file path |

## 5. Embeddings & RAG

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `EMBEDDING_PROVIDER` | server-only | A W | yes | `tei` | `tei` (production); `hash` allowed only in `test` |
| `EMBEDDING_ENDPOINT` | server-only | A W | if tei | `http://embeddings:80` | TEI base URL |
| `EMBEDDING_MODEL` | server-only | A W | yes | — (operator choice) | Model id served by TEI; recorded on rows |
| `EMBEDDING_DIMENSIONS` | server-only | A W, migrations | yes | — | Must match model output; fixed at migration |
| `EMBEDDING_API_KEY` | server-only (secret) | A W | no | — | If TEI is protected |
| `EMBEDDING_BATCH_SIZE` | server-only | W | no | `32` | |
| `EMBEDDING_QUERY_PREFIX` / `EMBEDDING_DOCUMENT_PREFIX` | server-only | A W | no | empty | Model-specific prefixes |
| `EMBEDDING_MODEL_NEXT` / `EMBEDDING_DIMENSIONS_NEXT` / `EMBEDDING_ENDPOINT_NEXT` | server-only | A W | only during an embedding-model migration | — | Target model for the `reembed` job (`21_VECTOR_SEARCH.md` §9); unset otherwise |
| `RERANKER_ENDPOINT` | server-only | A | no | — | Optional TEI reranker (Phase 11) |
| `RAG_SIM_THRESHOLD` | server-only | A | no | `0.25` | Calibrated per model |
| `RAG_TOP_K_VECTOR` / `RAG_TOP_K_FTS` / `RAG_FINAL_MAX_CHUNKS` / `RAG_MMR_LAMBDA` | server-only | A | no | `40` / `40` / `8` / `0.7` | |

## 6. Object storage & scanning

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `S3_ENDPOINT` | server-only | A W | yes (dev: RustFS) | `http://storage:9000` | Empty for AWS default endpoint |
| `S3_PUBLIC_ENDPOINT` | server-only | A N | no | `http://localhost:9000` (dev) | Browser-reachable endpoint for presigned URLs; Next.js uses its host for CSP |
| `S3_REGION` | server-only | A W | yes | `us-east-1` | |
| `S3_BUCKET` | server-only | A W | yes | `nova-dev` | |
| `S3_ACCESS_KEY` | server-only (secret) | A W | yes* | — | *Omit when using IAM roles in prod |
| `S3_SECRET_KEY` | server-only (secret) | A W | yes* | — | |
| `S3_FORCE_PATH_STYLE` | server-only | A W | no | `true` (dev) | Local S3-compatible storage needs path style |
| `CLAMAV_ENABLED` | server-only | W | no | `false` (dev), `true` (prod required) | |
| `CLAMAV_HOST` / `CLAMAV_PORT` | server-only | W | if enabled | `clamav` / `3310` | |

## 7. Tools

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `WEB_SEARCH_PROVIDER` | server-only | A | no | `none` | `searxng` \| `brave` \| `none` |
| `SEARXNG_URL` | server-only | A | if searxng | `http://searxng:8080` | |
| `BRAVE_SEARCH_API_KEY` | server-only (secret) | A | if brave | — | |
| `WEB_SEARCH_GLOBAL_RPS` | server-only | A | no | `10` | |
| `WEB_SEARCH_COST_PER_QUERY_USD_MICROS` | server-only | A | no | — | For cost tracking of paid providers |
| `SANDBOX_RUNNER_URL` | server-only | A | no | — | Enables `code_execution` tool when set |
| `SANDBOX_RUNNER_TOKEN` | server-only (secret) | A R | if runner | — | Bearer token shared api↔runner |
| `SANDBOX_RUNTIME` | server-only | R | no | `runsc` | `runc` allowed only in development/test |
| `SANDBOX_IMAGE` | server-only | R | yes | `nova-sandbox-python:latest` (dev) | Pinned digest in prod |
| `SANDBOX_MAX_CONCURRENCY` | server-only | R | no | `8` | |
| `SANDBOX_DOCKER_HOST` | server-only | R | no | `unix:///var/run/docker.sock` | |

## 8. Voice

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `VOICE_STT_PROVIDER` | server-only | A | no | `groq` if `GROQ_STT_MODEL` set else `none` | |
| `VOICE_TTS_PROVIDER` | server-only | A | no | `groq` if `GROQ_TTS_MODEL` set else `browser` | `groq` \| `browser` \| `none` |

## 9. Email

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `SMTP_HOST` | server-only | W | yes | `mailpit` | |
| `SMTP_PORT` | server-only | W | yes | `1025` | |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | server-only (secret) | W | prod | — | |
| `SMTP_FROM` | server-only | W | yes | `NOVA AI <no-reply@localhost>` | |
| `SMTP_USE_TLS` | server-only | W | no | `false` (dev), `true` (prod) | STARTTLS |

## 10. Payments (Razorpay)

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `RAZORPAY_KEY_ID` | server-only | A | Phase 10 | — | Returned to client in subscription create response |
| `RAZORPAY_KEY_SECRET` | server-only (secret) | A | Phase 10 | — | Signature verification, API calls |
| `RAZORPAY_WEBHOOK_SECRET` | server-only (secret) | A | Phase 10 | — | Webhook HMAC |
| `NEXT_PUBLIC_RAZORPAY_KEY_ID` | public, build-time | B | no | — | Optional; checkout uses the key id from API response when absent |

## 11. Observability

| Variable | Class | Svc | Required | Default | Description |
|---|---|---|---|---|---|
| `SENTRY_DSN` | server-only | A W R | prod | — | Backend Sentry |
| `NEXT_PUBLIC_SENTRY_DSN` | public, build-time | B N | prod | — | Frontend Sentry (DSNs are not secrets but scoped to web project) |
| `SENTRY_ENVIRONMENT` | server-only | A W R N | no | `APP_ENV` | |
| `SENTRY_AUTH_TOKEN` | build-time (secret) | CI | prod builds | — | Source map upload only; never in runtime env |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | server-only | A W R N | prod | — | |
| `OTEL_EXPORTER_OTLP_HEADERS` | server-only (secret) | A W R N | if backend needs auth | — | |
| `OTEL_SERVICE_NAME` | server-only | all | no | per service (`nova-api`, …) | |
| `OTEL_TRACES_SAMPLER` / `OTEL_TRACES_SAMPLER_ARG` | server-only | all | no | `parentbased_traceidratio` / `0.1` | |

## 12. Public web variables (complete allow-list)

| Variable | Description |
|---|---|
| `NEXT_PUBLIC_APP_URL` | Same value as `APP_URL` |
| `NEXT_PUBLIC_APP_NAME` | `NOVA AI` |
| `NEXT_PUBLIC_SENTRY_DSN` | Frontend DSN |
| `NEXT_PUBLIC_RAZORPAY_KEY_ID` | Razorpay public key id |

No other `NEXT_PUBLIC_*` variables may be added without updating this list.

## 13. Evaluation & CI

| Variable | Class | Where | Description |
|---|---|---|---|
| `EVAL_API_KEY` | secret | nightly CI | NOVA API key of the eval user on staging |
| `EVAL_MAX_COST_USD` | config | nightly CI | Budget cap |
| `STAGING_URL` | config | CI | Target for k6/ZAP/evals |

## 14. Validation rules by environment (`Settings.validate_for_env`)

In `staging`/`production` the process refuses to start if:
- `AUTH_SECRET` or `API_PROXY_SHARED_SECRET` shorter than 32 bytes or equal to example values.
- `APP_URL` not `https://`.
- `GROQ_BASE_URL` set; `EMBEDDING_PROVIDER=hash`; `SANDBOX_RUNTIME=runc` (runner).
- `CLAMAV_ENABLED` false (production only).
- `SENTRY_DSN` or `OTEL_EXPORTER_OTLP_ENDPOINT` missing (production only; warning in staging).
- `DATABASE_URL` uses the superuser or `REDIS_URL` lacks auth/TLS (production).
