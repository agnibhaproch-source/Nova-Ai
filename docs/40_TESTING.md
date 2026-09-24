# 40 — Testing Strategy

## 1. Test pyramid

| Layer | Tooling | Location | Runs |
|---|---|---|---|
| Backend unit | pytest, pytest-asyncio | `apps/api/tests/unit` | every PR |
| Backend integration (DB/Redis/S3) | pytest + real Postgres(pgvector) + Redis + MinIO (Compose services) | `apps/api/tests/integration` | every PR |
| API tests (HTTP contract) | pytest + HTTPX `AsyncClient(transport=ASGITransport(app))` | `apps/api/tests/api` | every PR |
| Security tests | pytest | `apps/api/tests/security` | every PR |
| Sandbox runner tests | pytest | `apps/sandbox-runner/tests` | every PR (runc); nightly (gVisor) |
| Frontend unit/component | Vitest + React Testing Library + MSW | `apps/web/tests` | every PR |
| E2E | Playwright | `apps/web/e2e` | every PR (Chromium desktop + mobile); nightly full matrix |
| Load | k6 | `infra/k6` | nightly against staging; before releases |
| AI evaluation | `evals/` | `evals/` | nightly + on model/prompt changes (`41_AI_EVALUATION.md`) |

## 2. Backend test infrastructure

- `docker-compose.test.yml` provides `postgres` (pgvector image), `redis`, `minio`; CI uses the same via service containers.
- Database: a fresh schema per test session via `alembic upgrade head`; each test runs inside a transaction with SAVEPOINT rollback (`AsyncSession` bound to a connection with nested transactions) for isolation and speed. Tests needing committed data across sessions (workers) use `truncate_all()` fixture.
- Redis: `FLUSHDB` on DB index 15 between tests.
- MinIO bucket `nova-test` recreated per session.
- Factories: plain async factory functions in `tests/factories.py` (`create_user(...)`, `create_conversation(...)`, …) — no global state.
- Clock: `app.core.clock` injected; tests use `freezegun`-style fixture `frozen_time`.
- Settings: `APP_ENV=test`, loaded from `apps/api/.env.test` (committed, no secrets).

## 3. Test doubles policy

- Allowed only under `tests/` (backend) and `apps/web/tests`, `apps/web/e2e/fixtures` (frontend).
- **Groq:** `tests/fakes/groq_stub_server.py` — an ASGI app implementing the subset of Groq's OpenAI-compatible endpoints we use (`POST /openai/v1/chat/completions` stream + non-stream, `GET /openai/v1/models`, audio endpoints), driven by scripted scenarios (text, tool calls split across chunks, usage in final chunk, 429 with retry-after, 500, stall for timeout, disconnect detection). Used by pointing `GROQ_BASE_URL` at it (test env only). Verify path prefixes against the SDK's default base URL before implementing the stub.
- **Embeddings:** `HashEmbeddingProvider` (deterministic).
- **Search provider:** `respx` mocks of provider HTTP.
- **Sandbox:** unit tests fake Docker client; integration uses real runner with `runc`.
- **Razorpay:** `respx` mocks + real signature computations with test secrets.
- Production settings validation refuses `GROQ_BASE_URL`, `EMBEDDING_PROVIDER=hash`, and test flags when `APP_ENV ∈ {staging, production}` (tested).

## 4. What to test (by area)

| Area | Must-have tests |
|---|---|
| Auth | signup/login/logout; lockout; generic errors; session expiry idle/absolute; revocation (cache invalidation); password reset single-use; CSRF required/validated; Origin checks; API key auth & scopes |
| Conversations | CRUD, pagination keyset correctness (no dupes/gaps under inserts), search ranking, trash/restore/purge |
| Messages | tree insertion, sibling index, branch switching, edit/regenerate flows, idempotency, concurrent submit → 409 |
| Streaming | event order, coalescing, resume from any Last-Event-ID, snapshot path, cancellation latency (< 500 ms with stub), client disconnect continues generation, reaper marks interrupted, degraded mode without Redis |
| Groq | `14_GROQ_INTEGRATION.md` §16 checklist |
| Context | budget allocation table-driven tests; summary validity on branches; overflow errors; delimiter neutralization |
| Files | initiate validations; complete with size mismatch; magic mismatch; zip bomb; encrypted PDF; per-format extraction fixtures (`tests/fixtures/files/`), chunk boundaries (no cross-page merge), idempotent reprocess |
| RAG | hybrid retrieval returns expected chunk for fixture corpus; threshold; citation mapping; permission isolation |
| Memory | extraction ops validation; sensitive filter; dedupe; toggle off |
| Tools | registry availability matrix; validation errors; timeouts; per-turn limits; calculator safety (reject `__import__`, attribute access, huge exponent) |
| Web search | normalization, dedupe, SSRF rejection, robots, caching |
| Rate limits/quotas | `34` §9, `35` §10 |
| Billing | subscription create (mock), verify signature valid/invalid, webhook signature, idempotent duplicates, state transitions, plan activation/downgrade |
| Admin | role enforcement on every route, audit rows for every mutation, content access requires reason |
| Errors | envelope format; no stack traces; constraint mapping |
| Logging | secrets redaction |

## 5. API contract tests

- Snapshot the OpenAPI schema (`tests/api/test_openapi_snapshot.py`) — changes require updating the snapshot and `31_API_ENDPOINTS.md` in the same PR.
- For each endpoint in `31_API_ENDPOINTS.md`: happy path status + envelope shape, auth required, documented errors.

## 6. Security tests (`tests/security`)

- **Authz matrix:** parametrized over every user-owned resource endpoint: user B attempting A's resource → 404; API key without scope → 403; support role on admin-mutation → 403.
- **Route inventory:** every route has an auth dependency or is on the public allow-list; every `/admin` route has a role dependency; every unsafe session route has CSRF.
- **RAG isolation:** two users with near-identical documents; queries never return the other's chunks (including via `file_ids` injection).
- **SSRF:** URLs resolving to 127.0.0.1, 10/8, 169.254.169.254, `[::1]`, IPv4-mapped IPv6, decimal/octal IP encodings, redirect to internal, DNS rebinding (resolver fake returning public then private) → blocked.
- **XSS:** frontend test renders a corpus of malicious markdown (`<script>`, `javascript:` links, `onerror` attributes, data URLs, SVG) → no script execution/no dangerous attributes.
- **Uploads:** polyglot files, mismatched extensions, oversized declared vs actual, macro docs.
- **Sandbox escape suite** (`24_CODE_EXECUTION.md` §11).
- **Secrets:** built web bundle scan; logs redaction; `/openapi.json` disabled in production config.
- **Headers:** CSP and security headers present on web responses.
- **Nightly:** OWASP ZAP baseline against staging.

## 7. Frontend tests

- Unit: SSE parser (split at every byte), stream-store reducers, error mapping, date grouping, shortcut registry.
- Component: Composer (enter/shift-enter/IME, attachments, disabled states), MessageItem variants (pending/streaming/stopped/failed/length), CodeBlock copy, CitationMarker popover, BranchNavigator, settings forms validation.
- MSW handlers emulate API + SSE streams (test-only).
- Accessibility: `vitest-axe` on key components.

## 8. E2E (Playwright)

Environment: full Compose stack with `APP_ENV=test` and the Groq stub server; seeded data via API.

Specs (each runs on desktop Chromium and mobile WebKit in nightly; desktop Chromium + mobile Chrome on PRs):
1. `journeys.spec.ts` — signup → settings persist → chat, edit, regenerate → rename/search/delete/undo → logout → login → reset password via the Mailpit email. `smoke.spec.ts` visits every route and fails on errors.
2. `chat.spec.ts` — send message, streaming visible, title appears, reload mid-stream resumes, stop, regenerate, edit branch navigation.
3. `files-rag.spec.ts` — upload PDF, wait ready, ask question, citation popover shows page.
4. `tools.spec.ts` — web search (stub provider), code execution (runner with runc), calculator.
5. `settings.spec.ts` — preferences, memories manage, sessions revoke, API key create/revoke, data export, delete account.
6. `limits.spec.ts` — quota exceeded UI, rate limit countdown.
7. `admin.spec.ts` — admin access, suspend user (user's session invalidated), non-admin gets 404 page.
8. `billing.spec.ts` — upgrade flow with Razorpay test mode (nightly only against staging with Razorpay test keys; PR runs use a stubbed checkout page served by the test fixture server).
9. `security.spec.ts` — network assertion: no requests to Groq domains from the browser (`page.on('request')` allow-list: same origin, S3 public endpoint, Sentry, Razorpay domains).
10. `a11y.spec.ts` — axe on landing, login, chat, settings, admin (0 serious/critical).
11. `responsive.spec.ts` — no horizontal overflow; sidebar modes.

## 9. Coverage expectations

| Scope | Line | Branch |
|---|---|---|
| Backend overall (`app/`) | ≥ 80% | ≥ 70% |
| Critical modules: `app/core/security.py`, `app/api/deps.py`, `services/auth_service.py`, `services/chat_service.py`, `services/generation_runner.py`, `streaming/*`, `ai/groq/*`, `services/context_service.py`, `services/rag_service.py`, `repositories/chunk_repository.py`, `tools/engine.py`, `tools/calculator.py`, `search/fetcher.py`, `ratelimit/*`, `services/quota_service.py`, `services/billing_service.py`, `api/v1/webhooks.py` | ≥ 90% | ≥ 85% |
| Frontend `lib/` | ≥ 90% | ≥ 80% |
| Frontend overall | ≥ 70% | ≥ 60% |

Enforced in CI via `pytest --cov --cov-fail-under` (per-module thresholds via `coverage` config + a small script) and Vitest coverage thresholds. Coverage is a floor, not a goal; critical behaviors must have explicit tests regardless.

## 10. Load tests (k6)

- `chat_stream.js`: ramp to 500 concurrent SSE streams against staging with Groq stub-backed staging-perf environment (to avoid Groq cost) **and** a small real-Groq run (20 VUs) nightly. Checks: TTFT p95, stream completion rate ≥ 99%, no 5xx.
- `api_read.js`: 200 RPS mixed reads (conversations list, messages, files) — p95 ≤ 300 ms.
- Rate-limit accuracy test.
- Results stored as CI artifacts; regressions > 20% fail the nightly job.

## 11. Running tests

`44_LOCAL_DEVELOPMENT.md` §8 lists commands (`make test`, `make test-api`, `make test-web`, `make e2e`, `make load`).
