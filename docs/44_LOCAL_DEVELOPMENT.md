# 44 — Local Development

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Git | ≥ 2.40 | |
| Docker Desktop / Docker Engine + Compose v2 | Engine ≥ 25 | ≥ 8 GB RAM allocated (embeddings + Postgres + app) |
| Node.js | 22 LTS | via `fnm`/`nvm`; `.nvmrc` at repo root |
| pnpm | ≥ 9 | `corepack enable` |
| Python | 3.12 | via `uv python install 3.12` |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh | sh` (or package manager) |
| make | any | |
| k6 | latest | load tests only |
| Groq API key | — | From your Groq console; for real chat locally |

## 2. Clone

```bash
git clone git@github.com:<org>/nova-ai.git
cd nova-ai
```

## 3. Environment setup

```bash
cp .env.example .env
ln -s ../../.env apps/web/.env   # Next.js reads its own directory's .env; share the root file in dev
```

Edit `.env`:
1. `GROQ_API_KEY` — your key (never commit).
2. `GROQ_DEFAULT_MODEL`, `GROQ_FAST_MODEL` — model IDs from current Groq documentation.
3. Fill `apps/api/config/models.yaml` `null` values required for your chosen models (`15_MODEL_CONFIGURATION.md` §4) — or run `make models-check` to see which are missing.
4. `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` — your chosen open-weights embedding model and its dimension.
5. Generate secrets:
   ```bash
   make secrets   # prints random AUTH_SECRET, API_PROXY_SHARED_SECRET, SANDBOX_RUNNER_TOKEN to paste into .env
   ```
6. Optional: `WEB_SEARCH_PROVIDER=searxng`, `SANDBOX_RUNNER_URL=http://sandbox-runner:8090` (with `make up-tools`).

## 4. Install dependencies (for IDE support, linting, and running tests outside Docker)

```bash
pnpm install                     # root + apps/web
cd apps/api && uv sync && cd -   # creates apps/api/.venv
cd apps/sandbox-runner && uv sync && cd -
pre-commit install               # via `uv tool install pre-commit`; runs gitleaks, ruff, prettier on commit
```

## 5. Database setup

Started by Compose; extensions created by `infra/docker/postgres/init/001_extensions.sql` and migration `0001`.

```bash
make up          # starts stack; `migrate` service runs alembic upgrade head
make seed        # python scripts/seed_dev.py: admin user (admin@nova.local / printed random password), sample conversation — refuses unless APP_ENV=development
```

## 6. Migrations

```bash
make revision m="describe change"   # autogenerate in apps/api/alembic/versions — REVIEW the file
make migrate                        # upgrade head
make migrate-down                   # downgrade -1 (dev only)
make migrate-check                  # fails if models and migrations diverge (alembic check)
```

## 7. Starting services

```bash
make up            # web, api, worker, postgres, redis, minio, mailpit, embeddings
make up-tools      # + sandbox-runner and searxng (build sandbox image first: make sandbox-image)
make up-security   # + clamav (set CLAMAV_ENABLED=true)
```

URLs:
- App: http://localhost:3000
- API docs (dev only): http://localhost:3000/api/v1/docs (proxied; Swagger UI enabled only when `APP_ENV=development`)
- Mailpit: http://localhost:8025
- MinIO console: http://localhost:9001

Running web or api outside Docker (faster iteration): stop the container (`docker compose stop web`) and run `pnpm --filter web dev` with `API_INTERNAL_URL=http://localhost:8000`; or `cd apps/api && uv run uvicorn app.main:app --reload` with `.env` hostnames pointed at `localhost`.

## 8. Testing

```bash
make test          # all backend + frontend unit/integration tests
make test-api      # pytest (starts docker-compose.test.yml deps if not running)
make test-api k="test_streaming"   # filter
make test-web      # vitest
make e2e           # playwright against docker-compose.test.yml stack (groq-stub)
make e2e-ui        # playwright UI mode
make eval-smoke    # small eval run (needs real GROQ_API_KEY)
make load          # k6 against local stack (groq-stub)
make coverage      # coverage reports with thresholds
```

## 9. Linting, formatting, type checking

```bash
make lint          # ruff check (api, runner, evals) + eslint (web)
make format        # ruff format + prettier --write
make typecheck     # mypy --strict app/ + tsc --noEmit
make check         # lint + typecheck + test (what CI runs, minus e2e)
make api-types     # regenerate OpenAPI TS types (commit the result)
make providers-check   # scripts/check_forbidden_providers.sh
```

## 10. Building

```bash
make build         # docker compose build
make build-prod    # builds prod targets: nova-api, nova-web, nova-sandbox-runner, nova-sandbox-python
pnpm --filter web build   # standalone Next.js build (runs bundle secret check afterwards)
```

## 11. Common issues

| Symptom | Fix |
|---|---|
| `embeddings` unhealthy for long | First run downloads the model; check `make logs s=embeddings`; ensure enough RAM |
| API exits `startup.config_invalid` | Read the named variable in the log; check `.env` and `models.yaml` |
| `readyz` fails `migrations` | `make migrate` |
| Uploads fail with CORS | Re-run `minio-init`; confirm `APP_URL` matches browser origin |
| Streams buffer in browser | Ensure you're on `localhost:3000` (proxy) not a custom proxy that buffers |
| Code execution unavailable | `make sandbox-image && make up-tools`; set `SANDBOX_RUNNER_URL` |

## 12. Makefile targets (must exist)

`up, up-tools, up-security, down, reset, logs, build, build-prod, migrate, migrate-down, migrate-check, revision, seed, secrets, sandbox-image, api-types, models-check, providers-check, lint, format, typecheck, test, test-api, test-web, e2e, e2e-ui, eval-smoke, load, coverage, check`, plus operations targets `rollback env=<staging|production>` (wraps the ECS rollback in `47_DEPLOYMENT.md` §8; requires cloud credentials and human approval).
