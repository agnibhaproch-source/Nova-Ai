# 53 — Implementation Phases

Executable plan for `52_ROADMAP.md`. Each phase ends only when its acceptance criteria and `56_DEFINITION_OF_DONE.md` are satisfied. Work within a phase proceeds in the listed order (backend → API → frontend → tests), but every feature is delivered end-to-end before the phase closes.

## Status

| Phase | Status | Completed on | Notes |
|---|---|---|---|
| 1 Foundation | implemented | — | Auth, settings, admin, Dockerfiles, CI/security/nightly workflows, Playwright. Pending: staging deploy (no target infra yet) |
| 2 Chat | implemented | — | BYOK per chat (ADR 0001), `openai/gpt-oss-120b`; E2E green against the Groq stub. Pending: live run with a real key in CI (`ci-evals`) |
| 3 Files | implemented | — | Presigned upload, validation, processing pipeline, attachment UI, Files settings. ClamAV optional (compose profile `security`) |
| 4 RAG | implemented | — | Hybrid FTS + pgvector with citations UI; embeddings need a TEI model (`EMBEDDING_MODEL`), else full-text only |
| 5 Memory | implemented | — | Extraction, filters, management UI, "Memory updated" notifications |
| 6 Tools | implemented | — | Calculator, file search, tool activity UI, per-message toggles |
| 7 Search | implemented | — | SearXNG/Brave provider with SSRF-safe fetch; off until `WEB_SEARCH_PROVIDER` is set |
| 8 Code execution | implemented | — | Sandbox runner verified on real Docker (network off, read-only, OOM, fork bomb, timeout). gVisor required in staging/prod |
| 9 Voice & vision | implemented | — | Needs `GROQ_KEY_MODE=server` + STT/TTS model IDs; BYOK falls back to browser read-aloud; vision needs `GROQ_VISION_MODEL` |
| 10 Billing & API access | implemented | — | Razorpay checkout/webhooks, API keys; needs Razorpay keys + plan ids to take payments |
| 11 Production scaling | implemented | 2026-09-25 | Admin console, k6 (`infra/k6`), evals (`evals/`), runbooks, single-server production stack + deploy workflow (`infra/deploy`, verified in production mode over HTTPS), AWS Terraform (`infra/terraform`, validated; not applied), DR drill passed (docs/runbooks/restore-from-backup.md), ZAP baseline scan: 0 failures (security headers, POST auth forms, default CSP). Needs a real deploy target (server or AWS account + domain) |
| Extra: Quick Chat & desktop | implemented | 2026-09-25 | In-page draggable window with hover-only controls, history and settings (27 §17a), browser extension (§17b), desktop app for Mac/Windows/Linux with passkey gate, Option+/ / Option+\\ / Option+Shift+Q, capture exclusion, background mode, signed Mac build (§17c), screenshots → vision incl. screenshot-only messages (§17d), drag and drop. No email verification (ADR 0002). Installers on /download. Needs Apple Developer ID / Windows code signing for warning-free installs |

Update this table when a phase completes (`00_MASTER_INSTRUCTION.md` §6).

---

## Phase 1 — Foundation

**Objectives:** runnable monorepo with Docker dev stack; CI; FastAPI + Next.js skeletons wired through the BFF proxy; database with migrations; complete authentication and user account basics; cross-cutting infrastructure (errors, logging, telemetry, rate limiting, audit); admin shell; staging deployment.

**Dependencies:** none.

**Files affected (create):**
- Root: `package.json`, `pnpm-workspace.yaml`, `Makefile`, `docker-compose.yml`, `docker-compose.test.yml`, `.env.example`, `.gitignore`, `.dockerignore`, `.editorconfig`, `.gitleaks.toml`, `.nvmrc`, `.github/workflows/{ci,security,deploy}.yml`, `.github/pull_request_template.md`, `.github/CODEOWNERS`, `scripts/{check_forbidden_providers.sh,check_bundle_secrets.sh,seed_dev.py}`, `infra/docker/postgres/init/001_extensions.sql`, `docs/adr/0001-record-architecture-decisions.md`.
- API: `app/main.py`, `app/core/*`, `app/db/*`, `app/models/{user,session,email_token,preferences,plan,audit_log,system_setting,analytics_event}.py`, `app/schemas/{common,auth,users}.py`, `app/repositories/{user,session,email_token,preferences,audit}_repository.py`, `app/services/{auth_service,user_service,session_service,email_service,audit_service,settings_service,analytics_service}.py`, `app/ratelimit/*`, `app/api/deps.py`, `app/api/v1/{router,auth,users,health,analytics,admin}.py` (admin: users list/detail/suspend only), `app/workers/settings.py`, `app/workers/tasks/{email,purge}.py`, `alembic/*`, `tests/*`, `Dockerfile`, `pyproject.toml`.
- Web: Next.js app scaffold, `src/app/layout.tsx`, `(marketing)/page.tsx`, `(auth)/*`, `(app)/layout.tsx`, `(app)/onboarding`, `(app)/chat/page.tsx` (app shell and empty state only; the composer is added in Phase 2 — Phase 1 is deployed to staging only, never to public users), `(app)/settings/{general,profile,personalization,security}`, `(admin)/admin/{page,users,users/[userId]}`, `app/api/v1/[...path]/route.ts`, `src/middleware.ts`, `src/components/ui/*`, `src/components/layout/*`, `src/lib/{api,auth,env,utils}`, `src/stores/ui-store.ts`, `src/features/{auth,settings,admin}`, `src/styles/globals.css`, test configs, `Dockerfile`.

**Database changes:** migrations `0001_extensions`, `0002_updated_at_trigger`, `0003_users_auth`, `0004_audit_system`, `0005_seed_plans`.

**APIs:** `/healthz`, `/readyz`; all `/auth/*`; `/users/me`, `/users/me/preferences`, `/users/me/password`, `/users/me/onboarding/complete`, `/users/me/sessions*`, `DELETE /users/me`, avatar endpoints deferred to Phase 3 (need files); `/analytics/events`; `/app-config`; `/admin/users`, `/admin/users/{id}` (GET/PATCH), `/admin/users/{id}/revoke-sessions`, `/admin/audit-logs`, `/admin/settings` (GET/PATCH).

**Backend:** Settings validation; middleware (request id, proxy secret, security headers, access log); error handlers & ErrorCode enum; structlog + redaction; OTel + Sentry init; UnitOfWork; auth (Argon2id, sessions, CSRF, lockout, verification, reset); rate limiter (GCRA + policies + fallback); audit service; settings service; email sender (SMTP) + templates (verify, reset); purge jobs for deleted users/sessions; ARQ worker skeleton with heartbeat.

**Frontend:** design tokens, theme provider (light/dark/system), shadcn components, landing page, auth pages, onboarding, app shell (sidebar skeleton, user menu), settings pages listed, admin shell + users pages, API client with CSRF + error mapping, generated OpenAPI types, security headers/CSP middleware.

**Tests:** auth unit/integration/API tests; CSRF; lockout; session revocation; authz route inventory test; redaction tests; rate limit tests; frontend auth form tests; E2E `auth.spec.ts`, `a11y.spec.ts` (landing, login), `security.spec.ts` (no Groq domains — trivially true now, keeps guard in place).

**Acceptance criteria:**
1. `make up` brings the stack up healthy on a clean machine following `44_LOCAL_DEVELOPMENT.md`.
2. User can sign up, log in, see the app shell, edit profile/preferences, list/revoke sessions, change/reset password, delete account.
3. Admin (bootstrap) can list users, suspend a user (their session is invalidated immediately), and see audit logs.
4. CI green: lint, typecheck, tests (coverage thresholds for auth modules ≥ 90%), build, E2E, security workflow.
5. Staging deployed via `deploy.yml` with smoke test passing (auth only).

---

## Phase 2 — Chat

**Objectives:** production-quality streamed chat on Groq with persistence, branching, cancellation, resume, titles, summaries, markdown rendering, search, feedback, model selection, usage tracking and quotas.

**Dependencies:** Phase 1.

**Files affected:**
- API: `app/models/{conversation,message,message_part,feedback,usage}.py`, `app/schemas/{conversations,messages,models,usage}.py`, `app/repositories/{conversation,message,feedback,usage}_repository.py`, `app/services/{conversation_service,message_service,chat_service,generation_runner,context_service,title_service,summary_service,usage_service,quota_service}.py`, `app/ai/**` (provider, registry, tokens, prompts, groq/*), `app/streaming/**`, `config/models.yaml`, `app/api/v1/{conversations,messages,models,usage}.py`, admin dashboard/usage endpoints, `app/workers/tasks/{title,summary,reaper,usage}.py`, `tests/fakes/groq_stub_server.py`.
- Web: `src/features/{chat,conversations,markdown,search,usage}/**`, `src/lib/sse/**`, `src/stores/{composer-store,stream-store}.ts`, `(app)/chat/page.tsx`, `(app)/c/[conversationId]/page.tsx`, `(app)/settings/{usage,data}` (archive/trash), sidebar conversation list, command palette, `(admin)/admin/{page,usage}`.

**Database changes:** `0006_chat`, `0007_usage`.

**APIs:** conversations (all in `31` §5 except files sub-resources), messages (`31` §6 except `/messages/{id}/memories`), `/models`, `/capabilities` (text-only capabilities), `/usage/*`, `/conversations/search`, `/conversations/bulk-delete`, `/admin/dashboard`, `/admin/usage`, `/admin/conversations` (metadata + content with reason), `/admin/models`, `/admin/plans` (read), `/admin/errors` (chat sources).

**Backend:** ModelRegistry + validation; GroqService/Provider with streaming, retries, fallback, circuit breaker, usage extraction; ContextService (system prompt, history, summary, budgets); GenerationRunner with broker (Redis Streams), checkpoints, cancellation, reaper; idempotency; conversation lock; title & summary jobs; quota counters and enforcement; usage records & daily aggregation; analytics events for chat.

**Frontend:** chat view, message list/items with all states, markdown/code/math rendering, composer (text only; attach button hidden until Phase 3), stop/regenerate/edit/branch navigator, resume on reload, auto-scroll, sidebar with grouping/infinite scroll/rename/pin/archive/delete, trash & archive dialogs, search palette, feedback dialog, usage page, quota warnings, model picker.

**Tests:** Groq checklist (`14` §16); streaming tests (`40` §4); context budget tests; message tree tests; quota tests; component tests for chat UI; E2E `chat.spec.ts`, `limits.spec.ts`; k6 `chat_stream.js` baseline (stub).

**Acceptance criteria:**
1. AC-02, AC-03, AC-04, AC-07, AC-08 from `02_PRD.md` pass.
2. TTFT p95 ≤ 2 s on staging with real Groq for a short prompt (measured over 50 requests).
3. Title appears within 5 s of first response completion.
4. A 200-message conversation loads in < 1 s and scrolls smoothly (virtualization).
5. Nightly live Groq smoke green.

---

## Phase 3 — Files

**Objectives:** secure uploads to S3 via presigned POST, validation, malware scanning, file library, attachments to conversations/messages, download/delete, avatars, data export.

**Dependencies:** Phase 2 (attachments to messages).

**Files affected:** API `app/models/{file,conversation_file,moderation_flag,data_export}.py`, `app/files/{storage,validation,scanner}.py`, `app/services/{file_service,export_service,moderation_service}.py`, `app/api/v1/files.py`, conversation file sub-routes, avatar routes, export routes, `/messages/{id}/report`, `app/workers/tasks/{files,exports}.py` (validation/scan stage + image derivatives; document stages come in Phase 4), purge file jobs. Web `src/features/files/**`, attachment tray/chips, library dialog, drag-and-drop, avatar uploader, export UI, report dialog. Infra: storage-init bucket CORS, ClamAV service.

**Database changes:** `0008_files`, `0009_moderation_exports`.

**APIs:** `31` §7 (all), conversation files sub-resources, avatar, exports, message report, `/admin/moderation/flags*`.

**Backend:** FileService (initiate/complete/list/get/download/content-url/retry/delete), validation pipeline, ClamAV integration, image derivative generation, storage quota counters, orphan cleanup, export job, moderation flags service.

**Frontend:** upload with progress (XHR), status polling, attachment chips in composer and messages, image thumbnails + lightbox (display only), library dialog, settings data export, profile avatar.

**Tests:** validation matrix (types, sizes, mismatch, zip bomb, macros, encrypted PDF detection), presigned POST flow against the S3-compatible dev storage (RustFS), ownership tests, deletion purge, export ZIP contents (AC-11), E2E upload flow.

**Acceptance criteria:**
1. Uploading each supported type succeeds end-to-end. In this phase the worker runs only the validation + scan stages; documents then become `ready` with `files.metadata.indexed=false` (downloadable and attachable; the UI labels them "Not indexed yet"). Phase 4 adds extraction/indexing, after which `ready` always means indexed and the label disappears.
2. Unsupported/mismatched files rejected with correct codes.
3. Malware test file (EICAR) rejected when ClamAV enabled.
4. Export ZIP correct; account deletion purges S3 prefix.

---

## Phase 4 — RAG (MVP completion)

**Objectives:** document processing for PDF, DOCX, TXT, MD, CSV, XLSX, PPTX; embeddings via TEI; pgvector hybrid retrieval; citations end-to-end.

**Dependencies:** Phase 3.

**Files affected:** API `app/documents/**`, `app/embeddings/**`, `app/models/document_chunk.py`, `app/repositories/chunk_repository.py`, `app/services/rag_service.py`, `app/services/rag_ranking.py`, `app/api/v1/rag.py`, ContextService RAG integration, StreamProcessor citation mapping, `process_file` full pipeline, `requeue_stuck_files` cron. Web `src/features/markdown/components/citation-marker.tsx`, `sources-footer.tsx`, `source-panel.tsx`, file-processing stage labels. Evals: `evals/` scaffold + `rag_docs`, `rag_unanswerable` suites.

**Database changes:** `0010_chunks_vector` (requires `EMBEDDING_DIMENSIONS`).

**APIs:** `/rag/search`; file endpoints now expose `stage/progress/chunk_count`.

**Backend:** extractors per format in process pool; normalizer; chunker; EmbeddingService (TEI) with cache; chunk indexing; hybrid retrieval (vector + FTS + RRF + MMR); permission filters; query rewrite; citation resolution; file "indexed" semantics finalized (`ready` = indexed for documents).

**Frontend:** citation markers/popovers/sources footer/source panel; "Searching your documents" activity row; file processing states.

**Tests:** extraction fixtures for each format; chunker invariants; retrieval tests on fixture corpus; RAG isolation security test; citation mapping; E2E `files-rag.spec.ts`; eval baseline for RAG suites recorded.

**Acceptance criteria:** AC-05, AC-06; retrieval p95 ≤ 400 ms (NFR-005); RAG eval baseline committed; **MVP (M2) exit review** held against `02_PRD.md` §6.

---

## Phase 5 — Memory

**Objectives:** controllable long-term memory.

**Dependencies:** Phase 4 (embeddings).

**Files affected:** API `app/models/memory.py`, `app/repositories/memory_repository.py`, `app/services/{memory_service,memory_triggers,sensitive_filter}.py`, `app/api/v1/memories.py`, `/messages/{id}/memories`, `app/workers/tasks/memory.py` (extract, decay, purge), ContextService P7. Web `src/features/memory/**`, personalization settings, "Used memory" indicator, toasts.

**Database changes:** `0011_memories`.

**APIs:** `31` §9, `/messages/{id}/memories`.

**Tests:** `17` §9; eval suite `memory_extraction` baseline.

**Acceptance criteria:** memory created from explicit "remember" request and used in a new conversation; no memory created for 95%+ of non-qualifying turns in eval; sensitive items rejected; toggle off stops extraction and retrieval immediately; delete/undo works.

---

## Phase 6 — Tools

**Objectives:** secure tool framework with calculator and file_search.

**Dependencies:** Phase 4 (file_search uses RAG).

**Files affected:** API `app/tools/{base,registry,engine,calculator,file_search}.py`, `app/models/tool_call.py`, repository, GenerationRunner tool loop, ContextService tool fitting, `/tools` endpoint, admin errors (tools). Web `tool-activity.tsx`, result views, composer tool toggles (UI placeholders for web/code hidden until their phases).

**Database changes:** `0012_tool_calls`.

**APIs:** `/tools`; SSE `tool_start`/`tool_result` events enabled.

**Tests:** registry availability matrix; validation/timeouts/limits; calculator safety; tool loop with stub (multi-iteration, parallel calls); E2E calculator; eval `tool_use` baseline.

**Acceptance criteria:** tool calls persisted and rendered; denied tools reported gracefully; tool loop bounded; no path to execute unregistered functions (code review + tests).

---

## Phase 7 — Search

**Objectives:** web search tool with citations.

**Dependencies:** Phase 6.

**Files affected:** `app/search/**` (service, providers, SafeFetcher), `app/tools/web_search.py`, SearXNG compose/config, Web `web-search-result-view.tsx`, composer globe toggle.

**Database changes:** none.

**Tests:** provider adapters (respx), normalization, SSRF suite, robots, caching, quota; E2E tools.spec (search); eval `web_search`.

**Acceptance criteria:** time-sensitive question triggers search and answer cites sources with working links; SSRF tests pass; provider failure handled with honest message.

---

## Phase 8 — Code execution

**Objectives:** sandboxed Python execution.

**Dependencies:** Phase 6.

**Files affected:** `apps/sandbox-runner/**`, `infra/docker/sandbox-python/Dockerfile`, `app/sandbox/client.py`, `app/tools/code_execution.py`, Web `code-run-block.tsx`, composer code toggle; production: sandbox ASG runbook with gVisor.

**Database changes:** none.

**Tests:** runner unit/integration; escape suite; timeout/OOM/output caps; cancellation; E2E code execution; eval `code_execution`.

**Acceptance criteria:** `24_CODE_EXECUTION.md` §11 security tests pass in CI (runc) and nightly (gVisor); staging runner uses runsc; plots render inline.

---

## Phase 9 — Voice & vision

**Objectives:** dictation, voice mode, read aloud; image understanding with a configured vision model; capabilities endpoint complete.

**Dependencies:** Phase 2 (chat), Phase 3 (images stored).

**Files affected:** `app/services/voice_service.py`, `app/voice/{stt,tts}.py` (providers), `app/api/v1/voice.py`, GroqService audio methods, ContextService image inputs, `/capabilities` full; Web `src/features/voice/**`, voice mode dialog, image attach enablement, model auto-switch chip.

**Database changes:** none.

**Tests:** STT/TTS with stub; limits; markdown stripping for TTS; image flow with vision stub; capability gating; E2E dictation (fake media stream in Playwright), image question.

**Acceptance criteria:** features enabled only when configured (verified by toggling env); dictation p95 latency target (`26` §7); image questions answered by vision model; non-vision models never receive images.

---

## Phase 10 — Billing & API access

**Objectives:** Razorpay subscriptions, plan enforcement, payment history, API keys, analytics dashboards.

**Dependencies:** Phase 2 (quotas), Phase 1 (auth).

**Files affected:** `app/models/{subscription,payment,webhook_event,api_key}.py`, `app/billing/razorpay_gateway.py`, `app/services/{billing_service,api_key_service}.py`, `app/api/v1/{billing,webhooks,api_keys}.py`, API-key auth path in deps, jobs `sync_subscriptions`, `downgrade_halted_subscriptions`; admin subscriptions/payments/webhook events/analytics endpoints; `scripts/set_razorpay_plan_ids.py`. Web `src/features/{billing,api-keys}/**`, pricing page, billing & API keys settings, admin pages, analytics dashboard.

**Database changes:** `0013_billing`, `0014_api_keys`.

**APIs:** `31` §12, §13, admin billing/analytics endpoints.

**Tests:** signature verification, webhook idempotency & state machine, subscription lifecycle with mocked Razorpay, plan activation/downgrade, API key scopes/limits/revocation, E2E billing (nightly with Razorpay test mode), API-key SSE client test.

**Acceptance criteria:** AC-10; API key client can stream a chat (J10); keys revocable immediately; downgrade after halted grace; analytics funnel visible.

---

## Phase 11 — Production scaling & GA hardening

**Objectives:** operational excellence and launch readiness.

**Dependencies:** Phases 1–10.

**Work items:** Terraform (`infra/terraform/**`); full admin (health, errors, models toggle, plans edit, webhook reprocess, CSV exports); dashboards/alerts as code + runbooks (`docs/runbooks/*`); OTel collector config; k6 stage gates (`49` §11); partitioning readiness migrations for `usage_records`, `analytics_events`, `audit_logs` (created partitioned via expand/contract when S3 stage approaches); PgBouncer/RDS Proxy; read replica wiring (`DATABASE_READ_REPLICA_URL`); backup plans + monthly restore test automation; DR game day; ZAP + external penetration test; cost report script; global Groq concurrency governor; performance tuning (Lighthouse, bundle size); launch checklist.

**Database changes:** partitioning migrations (as needed), indexes found by `pg_stat_statements` review.

**Tests:** load tests at 2× expected peak; failover drills (RDS/Redis) in staging; restore test; security retest.

**Acceptance criteria:** SLOs met in staging load tests; all P1/P2 alerts have runbooks; restore drill RTO/RPO measured within targets; pen-test high/critical findings fixed; every item in `56_DEFINITION_OF_DONE.md` §3 (product-level) satisfied → GA.
