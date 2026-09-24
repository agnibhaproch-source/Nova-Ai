# 46 — CI/CD (GitHub Actions)

## 1. Workflows

| Workflow | Trigger | Purpose |
|---|---|---|
| `ci.yml` | `pull_request`, `push` to `main` | Lint, typecheck, tests, build, E2E |
| `security.yml` | `pull_request`, `push` to `main`, weekly schedule | Secret scan, dependency audit, SAST, image scan, forbidden-provider check |
| `deploy.yml` | `push` to `main` (→ staging); tag `v*` (→ production) | Build, push images, migrate, deploy |
| `nightly.yml` | cron `0 21 * * *` UTC (02:30 IST) | Live Groq smoke, full E2E matrix, evals, k6, ZAP |

PR checks never deploy and never receive production secrets. Deploy workflows use GitHub **Environments** (`staging`, `production`) with scoped secrets; `production` requires manual approval by a maintainer.

Concurrency: `concurrency: { group: ${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: true }` for CI; deploys are not cancelled mid-run (`cancel-in-progress: false`).

Path filters: backend jobs run when `apps/api/**`, `apps/sandbox-runner/**`, `infra/**`, `docs/**` (docs-only → skip heavy jobs via `dorny/paths-filter`) change; frontend when `apps/web/**` changes; both on `main`.

## 2. `ci.yml` jobs

```yaml
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres: { image: pgvector/pgvector:pg16, env: {POSTGRES_USER: nova, POSTGRES_PASSWORD: nova, POSTGRES_DB: nova_test}, ports: ["5432:5432"], options: >-
          --health-cmd "pg_isready -U nova" --health-interval 5s --health-retries 20 }
      redis: { image: redis:7-alpine, ports: ["6379:6379"] }
      minio: { image: "bitnami/minio:<pinned>", env: {MINIO_ROOT_USER: test, MINIO_ROOT_PASSWORD: testtesttest}, ports: ["9000:9000"] }
    steps:
      - checkout
      - setup uv + python 3.12 (cache)
      - uv sync --frozen (apps/api, apps/sandbox-runner)
      - ruff check . && ruff format --check .
      - mypy --strict app
      - alembic upgrade head && alembic check        # migrations apply & match models
      - pytest -n auto --cov=app --cov-report=xml     # unit + integration + api + security
      - coverage thresholds script (40 §9)
      - sandbox-runner tests (runc; docker available on ubuntu runners)
  frontend:
    steps:
      - checkout; setup node 22 + pnpm (cache)
      - pnpm install --frozen-lockfile
      - pnpm --filter web lint && pnpm --filter web typecheck
      - pnpm --filter web test -- --coverage
      - make api-types && git diff --exit-code apps/web/src/lib/api/schema.d.ts   # generated types up to date (starts api via uv in background)
      - pnpm --filter web build (NEXT_PUBLIC_* dummy public values)
      - scripts/check_bundle_secrets.sh
      - bundle size check (NFR-008) via @next/bundle-analyzer JSON + script
  docker:
    steps:
      - docker buildx build (api prod, web prod, sandbox-runner, sandbox-python) with GHA cache; no push on PR
  e2e:
    needs: [backend, frontend]
    steps:
      - docker compose -f docker-compose.yml -f docker-compose.test.yml up -d --wait
      - pnpm --filter web exec playwright install --with-deps chromium
      - playwright test --project=desktop-chrome --project=mobile-chrome
      - upload traces/videos on failure
  eval-smoke:
    if: paths changed under app/ai, services/context_service.py, services/rag_service.py, documents/, tools/, config/models.yaml
    environment: ci-evals            # holds a low-quota GROQ_API_KEY; only for PRs from the same repo (not forks)
    steps: [make eval-smoke, post summary comment]
```

Fork PRs: secrets are unavailable; `eval-smoke` is skipped and must be run by a maintainer before merge.

## 3. Lint / typecheck / tests summary

| Check | Command | Blocking |
|---|---|---|
| Python lint/format | `ruff check`, `ruff format --check` | yes |
| Python types | `mypy --strict app` | yes |
| Migrations | `alembic upgrade head`, `alembic check` | yes |
| Backend tests + coverage | `pytest` | yes |
| TS lint | `eslint` (incl. import boundaries, `react/no-danger`) | yes |
| TS types | `tsc --noEmit` | yes |
| Frontend tests + coverage | `vitest run --coverage` | yes |
| Build | `next build`, docker builds | yes |
| E2E | Playwright (2 projects) | yes |
| OpenAPI snapshot / generated types | pytest + git diff | yes |

## 4. `security.yml`

| Job | Tool | Policy |
|---|---|---|
| Secrets | `gitleaks/gitleaks-action` with `.gitleaks.toml` (custom rules for `gsk_`, `nova_sk_`, `rzp_`) | block |
| Forbidden providers | `scripts/check_forbidden_providers.sh`: fails if lockfiles/imports/config reference `openai`, `anthropic`, `google-generativeai`, `google-genai`, `mistralai`, `cohere`, `together`, `litellm`, `langchain-openai`/`-anthropic`/`-google*`/`-mistralai`/`-cohere`, `@ai-sdk/*` providers, `api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`, `openrouter.ai`, `api.together`, `api.mistral.ai`, `api.cohere` in `apps/**` | block |
| Python deps | `pip-audit` (from `uv export`) | block high/critical with fix |
| Node deps | `pnpm audit --audit-level=high` | block |
| SAST | GitHub CodeQL (python, javascript-typescript) | block high |
| Container scan | Trivy on built images (vuln + secret + misconfig) | block critical with fix |
| IaC | Trivy config scan on Dockerfiles/compose | warn |
| License | `pip-licenses`/`license-checker` deny AGPL/GPL in runtime deps | block |

Waivers: documented in `security/waivers.yaml` with expiry date and ADR link.

## 5. `deploy.yml`

```
on push main → job build-and-push (environment: staging)
   build prod images (api, web if self-hosted, sandbox-runner, sandbox-python), tag :sha-<short> and :staging
   push to registry (reference: Amazon ECR via OIDC — no long-lived AWS keys)
   upload Sentry source maps (web) with SENTRY_AUTH_TOKEN
 → job migrate (staging): run one-off task with api image: `alembic upgrade head` using DATABASE_MIGRATOR_URL
 → job deploy (staging): update services (api, worker, sandbox-runner) to new image digest; web → Vercel deploy (preview → promote to staging alias)
 → job smoke (staging): scripts/smoke.sh: /readyz, signup/login with test account, send message (real Groq, low max tokens), upload small file → ready
on tag v* → same steps with environment: production (manual approval), images retagged from the already-tested sha (no rebuild), then smoke on production using a dedicated synthetic account
```

- Deploy strategy: rolling update with health checks (min healthy 100%, max 200%); API instances drain SSE connections with 30 s grace (`13_STREAMING.md` §4).
- Automatic rollback if post-deploy smoke fails or 5xx alert fires within 10 min (re-point services to previous task definition).
- Migrations must be backward compatible with the previous release (expand/contract), since old instances run during rollout.

## 6. `nightly.yml`

1. **Live Groq smoke:** `pytest -m live_groq` using `GROQ_API_KEY` (environment `nightly`): streaming, tool call, JSON mode, usage extraction, models verification against configured IDs.
2. **Full E2E matrix** (desktop Chromium, Firefox, WebKit, mobile Safari/Chrome) against compose test stack.
3. **Evals** on staging (`41_AI_EVALUATION.md` §8) with cost cap; report posted to Slack.
4. **k6** load scenarios against staging-perf; compare with previous results.
5. **OWASP ZAP baseline** against staging.
6. **gVisor sandbox tests** on a self-hosted runner with runsc.
7. Failure → Slack `#nova-ci` + GitHub issue auto-created (deduplicated).

## 7. Secrets in CI

| Secret | Environment |
|---|---|
| `GROQ_API_KEY` (low-quota key) | `ci-evals`, `nightly` |
| AWS OIDC role ARN | `staging`, `production` |
| `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | `staging`, `production` |
| `SENTRY_AUTH_TOKEN` | `staging`, `production` |
| `EVAL_API_KEY`, `STAGING_URL` | `nightly` |
| `SLACK_WEBHOOK_URL` | all non-PR |

Runtime secrets (DB, Groq prod key, Razorpay) live in the cloud secret manager, not in GitHub.
