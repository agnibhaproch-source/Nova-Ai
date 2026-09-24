# 43 — Docker

## 1. Services (development `docker-compose.yml`)

| Service | Image / build | Ports (host) | Purpose | Profile |
|---|---|---|---|---|
| `web` | build `apps/web` target `dev` | 3000 | Next.js dev server (hot reload) | default |
| `api` | build `apps/api` target `dev` | 8000 | FastAPI with `--reload` | default |
| `worker` | build `apps/api` target `dev` | — | ARQ worker with `watchfiles` reload | default |
| `migrate` | build `apps/api` target `dev` | — | One-shot `alembic upgrade head` | default |
| `postgres` | `pgvector/pgvector:pg16` | 5432 | Database | default |
| `redis` | `redis:7-alpine` | 6379 | Cache/queues/streams | default |
| `storage` | `rustfs/rustfs` (pinned) | 9000, 9001 | S3-compatible storage + console (ADR 0003) | default |
| `storage-init` | `amazon/aws-cli` (pinned) | — | Creates the bucket and its CORS rule (private by default) | default |
| `mailpit` | `axllent/mailpit` (pinned) | 8025 (UI), 1025 | Dev SMTP | default |
| `embeddings` | `ghcr.io/huggingface/text-embeddings-inference:<cpu tag pinned>` | 8081 | Embedding server running `EMBEDDING_MODEL` | default |
| `sandbox-runner` | build `apps/sandbox-runner` | 8090 | Code execution (dev mode, runc) | `tools` |
| `searxng` | `searxng/searxng` (pinned) | 8888 | Web search provider | `tools` |
| `clamav` | `clamav/clamav` (pinned) | — | Malware scanning | `security` |
| `groq-stub` | build `apps/api` target `dev`, command runs `tests/fakes/groq_stub_server.py` | 8099 | Test-only Groq emulator | `test` |

Implementation notes: `migrate`, `api`, `worker`, `web` run under the compose profile `app` (`make up`); `make infra` starts only the data services so the app can run on the host with hot reload (`make dev-api`, `make dev-worker`, `make dev-web`). Storage is RustFS (`rustfs/rustfs`, pinned), because MinIO stopped publishing container images (ADR 0003); the bucket is prepared by `storage-init` (`amazon/aws-cli`). Host ports for Postgres/Redis are configurable via `POSTGRES_HOST_PORT` / `REDIS_HOST_PORT` in `.env`.

The spec's minimum services (web, api, postgres, redis) are all present; the others are required for the documented features to function locally without fakes.

## 2. Dockerfiles

### 2.1 `apps/api/Dockerfile` (multi-stage)

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim@sha256:<digest> AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends libmagic1 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:<pinned> /uv /usr/local/bin/uv
WORKDIR /app

FROM base AS deps
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project --no-dev

FROM deps AS dev
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project
COPY . .
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS prod
RUN groupadd -g 10001 app && useradd -u 10001 -g app -s /usr/sbin/nologin -M app
COPY --from=deps /app/.venv /app/.venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY config ./config
ENV PATH="/app/.venv/bin:$PATH"
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "--graceful-timeout", "30", "--timeout", "0", "--keep-alive", "75"]
```
`--timeout 0` disables gunicorn's worker timeout (SSE streams are long-lived; server-side generation limits apply). The worker uses the same `prod` image with command `arq app.workers.settings.WorkerSettings`.

### 2.2 `apps/web/Dockerfile`

```dockerfile
FROM node:22-alpine@sha256:<digest> AS base
RUN corepack enable
WORKDIR /repo

FROM base AS deps
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY apps/web/package.json apps/web/
RUN --mount=type=cache,target=/root/.local/share/pnpm pnpm install --frozen-lockfile --filter web...

FROM deps AS dev
COPY apps/web apps/web
WORKDIR /repo/apps/web
CMD ["pnpm", "dev", "--hostname", "0.0.0.0"]

FROM deps AS build
COPY apps/web apps/web
WORKDIR /repo/apps/web
ARG NEXT_PUBLIC_APP_URL NEXT_PUBLIC_APP_NAME NEXT_PUBLIC_SENTRY_DSN NEXT_PUBLIC_RAZORPAY_KEY_ID APP_VERSION
RUN pnpm build            # next.config.ts: output: "standalone"

FROM node:22-alpine@sha256:<digest> AS prod
WORKDIR /app
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -g 10001 app && adduser -u 10001 -G app -D app
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public
USER 10001
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
```

### 2.3 `apps/sandbox-runner/Dockerfile`
Python 3.12 slim, installs `docker` (Docker SDK for Python), FastAPI, uvicorn; non-root user added to the docker group **only in dev compose** via `group_add`. In production the runner runs on dedicated hosts (`24_CODE_EXECUTION.md`).

### 2.4 `infra/docker/sandbox-python/Dockerfile`
See `24_CODE_EXECUTION.md` §3. Built as `nova-sandbox-python:<version>`; `make sandbox-image` for dev.

## 3. `docker-compose.yml` (key excerpts)

```yaml
name: nova
x-api-env: &api-env
  env_file: .env
  environment:
    DATABASE_URL: postgresql+asyncpg://nova:nova@postgres:5432/nova
    REDIS_URL: redis://redis:6379/0
    S3_ENDPOINT: http://storage:9000
    S3_PUBLIC_ENDPOINT: http://localhost:9000
    EMBEDDING_ENDPOINT: http://embeddings:80
    SMTP_HOST: mailpit
    SMTP_PORT: "1025"

services:
  postgres:
    image: pgvector/pgvector:pg16
    environment: { POSTGRES_USER: nova, POSTGRES_PASSWORD: nova, POSTGRES_DB: nova }
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./infra/docker/postgres/init:/docker-entrypoint-initdb.d:ro
    ports: ["5432:5432"]
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U nova -d nova"], interval: 5s, timeout: 3s, retries: 20 }

  redis:
    image: redis:7-alpine
    command: ["redis-server", "--appendonly", "yes", "--maxmemory-policy", "noeviction"]
    volumes: [redisdata:/data]
    ports: ["6379:6379"]
    healthcheck: { test: ["CMD", "redis-cli", "ping"], interval: 5s, timeout: 3s, retries: 20 }

  storage:                     # RustFS: S3-compatible (MinIO no longer publishes images; ADR 0003)
    image: rustfs/rustfs:1.0.0
    environment: { RUSTFS_ACCESS_KEY: ${S3_ACCESS_KEY}, RUSTFS_SECRET_KEY: ${S3_SECRET_KEY} }
    volumes: [storagedata:/data]
    ports: ["9000:9000", "9001:9001"]
    healthcheck: { test: ["CMD", "curl", "-fsS", "http://localhost:9000/health"], interval: 5s, timeout: 3s, retries: 20 }

  storage-init:                # creates the bucket + CORS for presigned uploads (infra/deploy/storage-init.sh)
    image: amazon/aws-cli:2.37.2
    depends_on: { storage: { condition: service_healthy } }
    env_file: .env
    environment: { S3_CORS_ORIGINS: "${APP_URL},http://localhost:3000,http://localhost:3100" }
    volumes: ["./infra/deploy/storage-init.sh:/storage-init.sh:ro"]
    entrypoint: ["/bin/sh", "/storage-init.sh"]

  embeddings:
    image: ghcr.io/huggingface/text-embeddings-inference:<cpu-version-pinned>
    command: ["--model-id", "${EMBEDDING_MODEL}", "--port", "80"]
    volumes: [hfcache:/data]
    ports: ["8081:80"]
    healthcheck: { test: ["CMD-SHELL", "curl -fsS http://localhost/health || exit 1"], interval: 10s, timeout: 3s, retries: 60 }

  mailpit:
    image: axllent/mailpit:<pinned>
    ports: ["8025:8025", "1025:1025"]

  migrate:
    build: { context: apps/api, target: dev }
    <<: *api-env
    command: ["uv", "run", "alembic", "upgrade", "head"]
    depends_on: { postgres: { condition: service_healthy } }
    restart: "no"

  api:
    build: { context: apps/api, target: dev }
    <<: *api-env
    volumes: ["./apps/api:/app", "/app/.venv"]
    ports: ["8000:8000"]
    depends_on:
      migrate: { condition: service_completed_successfully }
      redis: { condition: service_healthy }
      storage-init: { condition: service_completed_successfully }
      embeddings: { condition: service_healthy }
    healthcheck: { test: ["CMD-SHELL", "curl -fsS http://localhost:8000/healthz || exit 1"], interval: 10s, timeout: 3s, retries: 10 }

  worker:
    build: { context: apps/api, target: dev }
    <<: *api-env
    command: ["uv", "run", "watchfiles", "--filter", "python", "arq app.workers.settings.WorkerSettings", "app"]
    volumes: ["./apps/api:/app", "/app/.venv"]
    depends_on: { api: { condition: service_healthy } }

  web:
    build: { context: ., dockerfile: apps/web/Dockerfile, target: dev }
    env_file: .env
    environment: { API_INTERNAL_URL: http://api:8000 }
    volumes: ["./apps/web:/repo/apps/web", "/repo/apps/web/node_modules", "/repo/apps/web/.next"]
    ports: ["3000:3000"]
    depends_on: { api: { condition: service_healthy } }

  sandbox-runner:
    profiles: ["tools"]
    build: { context: apps/sandbox-runner }
    environment: { SANDBOX_RUNTIME: runc, SANDBOX_IMAGE: "nova-sandbox-python:dev", APP_ENV: development }
    env_file: .env
    volumes: ["/var/run/docker.sock:/var/run/docker.sock"]   # DEV ONLY — never in staging/production
    ports: ["8090:8090"]

  searxng:
    profiles: ["tools"]
    image: searxng/searxng:<pinned>
    volumes: ["./infra/docker/searxng/settings.yml:/etc/searxng/settings.yml:ro"]
    ports: ["8888:8080"]

  clamav:
    profiles: ["security"]
    image: clamav/clamav:<pinned>
    healthcheck: { test: ["CMD", "clamdcheck.sh"], interval: 30s, timeout: 10s, retries: 20 }

volumes: { pgdata: {}, redisdata: {}, storagedata: {}, hfcache: {} }
```

## 4. Networking

- Single default bridge network `nova_default`; services address each other by name.
- Host ports are exposed for developer tooling only. In production nothing but the load balancer is public.
- The browser uses `http://localhost:3000` (web) and `http://localhost:9000` (presigned storage URLs). API port 8000 is exposed for debugging but the API still requires `X-Nova-Proxy-Secret` (use `make api-shell`/curl helper that adds it).

## 5. Health checks & startup order

`postgres`/`redis`/`storage` healthy → `migrate` completes → `storage-init` completes → `embeddings` healthy (first start downloads the model; may take minutes) → `api` healthy → `worker`, `web`.

## 6. Volumes & data

Named volumes persist data across restarts. `make reset` runs `docker compose down -v` (destroys local data — confirmation prompt). `hfcache` caches embedding model weights.

## 7. Environment

`.env` at repo root (copied from `.env.example`) is shared by services; compose `environment:` overrides container-internal hostnames. Secrets in `.env` are dev-only values.

## 8. Development workflow

```bash
make up            # docker compose up -d --build (default profile)
make up-tools      # + sandbox-runner, searxng (profile tools)
make logs s=api    # follow logs
make migrate       # run migrations
make revision m="add x"   # alembic revision --autogenerate
make api-types     # regenerate apps/web/src/lib/api/schema.d.ts from running API OpenAPI
make down          # stop
```

Hot reload: api (`uvicorn --reload`), worker (`watchfiles`), web (`next dev`). Dependency changes require `make build`.

## 9. Test compose (`docker-compose.test.yml`)

Overrides: no bind mounts, `APP_ENV=test`, tmpfs for Postgres data (`/var/lib/postgresql/data` on tmpfs), `groq-stub` enabled, `EMBEDDING_PROVIDER=hash` (skips TEI), `CLAMAV_ENABLED=false`, `WEB_SEARCH_PROVIDER=searxng` pointed at a respx-like stub container for E2E (`search-stub`, also from `tests/fakes`).

## 10. Image hygiene

- Base images pinned by digest; weekly Renovate/Dependabot updates.
- `.dockerignore` excludes `.env*`, `.git`, `node_modules`, `.venv`, tests (prod stages), docs.
- Non-root users, read-only root filesystem in production (`/tmp` as tmpfs), no package managers invoked at runtime.
- Trivy scan in CI; fail on critical vulnerabilities with fixes available.
