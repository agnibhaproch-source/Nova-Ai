# 06 — Folder Structure

This is the exact repository layout. Create folders only when they receive their first real file; do not create empty placeholder folders. Paths are relative to the repo root `nova-ai/`.

## 1. Root

```
nova-ai/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                    # PR + main: lint, typecheck, tests, build, e2e
│   │   ├── security.yml              # gitleaks, CodeQL, pip-audit, pnpm audit, Trivy, provider-ban check
│   │   ├── deploy.yml                # main → staging; tag v* → production (environment approval)
│   │   └── nightly.yml               # live Groq smoke test, evals, k6 against staging
│   ├── pull_request_template.md
│   └── CODEOWNERS
├── apps/
│   ├── web/                          # Next.js frontend (see §2)
│   ├── api/                          # FastAPI backend + worker (see §3)
│   ├── sandbox-runner/               # Isolated code execution service (see §4)
│   ├── extension/                    # Quick Chat browser extension (MV3; docs/27 §17b)
│   └── desktop/                      # Nova desktop app (Electron; Option+/ Quick Chat, screenshots; 27 §17c)
├── infra/
│   ├── terraform/                    # Phase 11 IaC (47 §10)
│   ├── observability/{dashboards,alerts}/   # Phase 11 (39 §1)
│   ├── docker/
│   │   ├── sandbox-python/Dockerfile # Image used for user code containers
│   │   ├── postgres/init/001_extensions.sql
│   │   └── searxng/settings.yml
│   └── k6/
│       ├── chat_stream.js
│       ├── api_read.js
│       └── lib/auth.js
├── evals/                            # AI evaluation suites (41_AI_EVALUATION.md)
│   ├── datasets/*.jsonl
│   ├── fixtures/files/               # documents used by RAG evals
│   ├── datasets/human_labels/        # judge calibration labels (41 §4)
│   ├── baselines/<suite>.json        # committed baseline metrics
│   ├── nova_evals/                   # Python package: runner, scorers, judge prompts, report
│   └── pyproject.toml
├── scripts/
│   ├── check_forbidden_providers.sh  # fails if banned LLM SDKs/domains appear
│   ├── check_bundle_secrets.sh       # scans .next output for secret patterns
│   ├── seed_dev.py                   # dev seed (admin user, sample data) — refuses outside development
│   ├── smoke.sh                      # post-deploy smoke test (46 §5)
│   ├── set_razorpay_plan_ids.py      # 35 §5, 47 §9
│   ├── cost_report.py                # 51 §1
│   ├── restore_s3_prefix.py          # 50 §5.3
│   └── replay_purges.py              # 50 §7
├── docs/                             # 00–56 + adr/ + runbooks/
│   ├── adr/0001-record-architecture-decisions.md
│   └── runbooks/                     # created in Phase 11 (one per alert + security-incident.md)
├── docker-compose.yml                # dev stack
├── docker-compose.test.yml           # CI overrides (no volumes, test env)
├── Makefile                          # developer entrypoints (44_LOCAL_DEVELOPMENT.md)
├── pnpm-workspace.yaml
├── package.json                      # root scripts: lint, format, typecheck delegations
├── .env.example
├── .gitignore  .dockerignore  .editorconfig  .gitleaks.toml
├── README.md  CLAUDE.md  AGENTS.md
```

## 2. `apps/web`

```
apps/web/
├── src/
│   ├── app/                                   # Next.js App Router
│   │   ├── layout.tsx                         # <html>, fonts, ThemeProvider, QueryProvider, Toaster
│   │   ├── globals.css → ../styles/globals.css (imported)
│   │   ├── (marketing)/page.tsx               # Landing "/"
│   │   ├── (marketing)/pricing/page.tsx
│   │   ├── (auth)/layout.tsx                  # centered card layout; redirects if logged in
│   │   ├── (auth)/login/page.tsx
│   │   ├── (auth)/signup/page.tsx
│   │   ├── (auth)/forgot-password/page.tsx
│   │   ├── (auth)/reset-password/page.tsx     # ?token=
│   │   ├── (app)/layout.tsx                   # requires session (server check) → AppShell
│   │   ├── (app)/onboarding/page.tsx
│   │   ├── (app)/chat/page.tsx                # new chat
│   │   ├── (app)/c/[conversationId]/page.tsx  # conversation
│   │   ├── (app)/settings/layout.tsx
│   │   ├── (app)/settings/[section]/page.tsx  # general|profile|personalization|data|security|usage (+api-keys, billing in Phase 10)
│   │   ├── (admin)/admin/layout.tsx           # requires role admin|support (server check)
│   │   ├── (admin)/admin/page.tsx             # dashboard
│   │   ├── (admin)/admin/{users,users/[userId],usage,conversations,health,errors,subscriptions,payments,audit-logs,moderation,settings,models,plans,analytics}/page.tsx
│   │   ├── api/v1/[...path]/route.ts          # BFF proxy (GET/POST/PATCH/PUT/DELETE), streams SSE
│   │   ├── not-found.tsx  error.tsx  global-error.tsx
│   │   └── robots.ts  sitemap.ts
│   ├── components/
│   │   ├── ui/                                # shadcn/ui generated primitives (button, dialog, ...)
│   │   ├── layout/                            # AppShell, Sidebar, TopBar, AdminShell
│   │   └── common/                            # Logo, EmptyState, ErrorState, Spinner, KeyboardShortcut
│   ├── features/                              # feature modules (29_COMPONENT_ARCHITECTURE.md)
│   │   ├── auth/{api,components,hooks,schemas}/
│   │   ├── conversations/{api,components,hooks}/
│   │   ├── chat/{api,components,hooks,lib}/   # Composer, MessageList, MessageItem, stream handling
│   │   ├── markdown/{components,lib}/         # Markdown, CodeBlock, Math, CitationMarker
│   │   ├── files/{api,components,hooks}/
│   │   ├── memory/{api,components}/
│   │   ├── settings/{components}/
│   │   ├── billing/{api,components,lib}/      # Razorpay checkout loader
│   │   ├── api-keys/{api,components}/
│   │   ├── usage/{api,components}/
│   │   ├── voice/{components,hooks,lib}/      # MediaRecorder, playback
│   │   ├── search/{components}/               # command palette (Cmd+K)
│   │   ├── quick-chat/                        # "/" Quick Chat popup + /quick pop-out window (27 §17a)
│   │   └── admin/{api,components}/
│   ├── lib/
│   │   ├── api/client.ts                      # openapi-fetch client, CSRF header injection, error mapping
│   │   ├── api/schema.d.ts                    # GENERATED from FastAPI OpenAPI — do not edit
│   │   ├── api/errors.ts                      # ApiError class, code → message map
│   │   ├── query-keys.ts                      # TanStack Query key factory (29 §4)
│   │   ├── shortcuts.ts                       # keyboard shortcut registry (27 §17)
│   │   ├── sse/parser.ts                      # SSE line parser (fetch ReadableStream)
│   │   ├── sse/stream-client.ts               # POST+stream, resume with Last-Event-ID, backoff
│   │   ├── auth/server-session.ts             # server-side session check for layouts (calls /auth/session)
│   │   ├── analytics.ts                       # client event batching (no content)
│   │   ├── env.ts                             # zod-validated public env
│   │   └── utils.ts                           # cn(), formatters
│   ├── stores/{ui-store,composer-store,stream-store}.ts
│   ├── styles/globals.css                     # Tailwind + design tokens
│   └── proxy.ts                               # Next.js 16 "proxy" (formerly middleware): security headers/CSP nonce; fast redirect of unauthenticated users
├── public/{favicon.svg,og.png,logo.svg}
├── tests/{unit,components}/                   # Vitest + RTL + MSW
├── tests/e2e/                                 # Playwright specs (auth.setup, chat, quick-chat)
├── next.config.ts  tailwind config (in CSS for v4)  postcss.config.mjs
├── vitest.config.ts  playwright.config.ts  eslint.config.mjs  tsconfig.json
├── components.json                            # shadcn config
├── Dockerfile
└── package.json
```

## 3. `apps/api`

```
apps/api/
├── app/
│   ├── main.py                     # create_app(): middleware, routers, exception handlers, lifespan
│   ├── core/
│   │   ├── data/                   # common_passwords.txt, disposable_domains.txt
│   │   ├── config.py               # Settings (pydantic-settings); validates env per APP_ENV
│   │   ├── security.py             # hashing (argon2), token gen, HMAC helpers, constant-time compare
│   │   ├── errors.py               # AppError hierarchy + ErrorCode enum
│   │   ├── logging.py              # structlog config, redaction processor
│   │   ├── telemetry.py            # OTel + Sentry init
│   │   ├── middleware.py           # RequestId, ProxySecret, SecurityHeaders, AccessLog
│   │   └── clock.py                # utcnow() (injectable for tests)
│   ├── db/
│   │   ├── base.py                 # DeclarativeBase, naming convention, mixins (Timestamp, SoftDelete)
│   │   ├── session.py              # engine, async_sessionmaker, get_db dependency
│   │   └── uow.py                  # UnitOfWork with after_commit hooks
│   ├── models/                     # SQLAlchemy models, one module per aggregate
│   │   ├── user.py session.py email_token.py preferences.py plan.py
│   │   ├── conversation.py message.py message_part.py
│   │   ├── file.py conversation_file.py document_chunk.py
│   │   ├── memory.py tool_call.py usage.py subscription.py payment.py webhook_event.py
│   │   ├── feedback.py api_key.py audit_log.py analytics_event.py system_setting.py
│   │   └── moderation_flag.py data_export.py
│   ├── schemas/                    # Pydantic request/response models (mirrors routers)
│   ├── repositories/               # one repository per aggregate; all user-scoped methods take user_id
│   │   └── admin/                  # unscoped admin-only queries (36 §14)
│   ├── services/
│   │   ├── auth_service.py user_service.py session_service.py email_service.py
│   │   ├── conversation_service.py message_service.py chat_service.py generation_runner.py
│   │   ├── context_service.py memory_service.py title_service.py summary_service.py
│   │   ├── file_service.py rag_service.py usage_service.py quota_service.py
│   │   ├── billing_service.py api_key_service.py admin_service.py analytics_service.py
│   │   ├── audit_service.py export_service.py moderation_service.py settings_service.py
│   │   ├── rag_ranking.py memory_triggers.py sensitive_filter.py voice_service.py analytics_events.py
│   │   └── task_registry.py        # tracked background asyncio tasks (54 §3.7)
│   ├── ai/
│   │   ├── provider.py             # LLMProvider Protocol, ChatRequest/ChatChunk/ChatResult dataclasses
│   │   ├── models_registry.py      # ModelRegistry (loads config/models.yaml, env interpolation, validation)
│   │   ├── tokens.py               # TokenEstimator
│   │   ├── prompts/                # system prompt templates (*.md) + loader
│   │   └── groq/
│   │       ├── client.py           # AsyncGroq factory (singleton per process)
│   │       ├── provider.py         # GroqProvider implements LLMProvider
│   │       ├── converters.py       # internal messages/tools ↔ Groq wire format
│   │       ├── errors.py           # groq exceptions → ProviderError subclasses
│   │       └── service.py          # GroqService facade (retry, metrics, usage, logging)
│   ├── embeddings/{provider.py,tei.py,service.py}
│   ├── streaming/{events.py,broker.py,sse.py,stream_processor.py}
│   ├── tools/
│   │   ├── base.py                 # Tool protocol, ToolContext, ToolResult
│   │   ├── registry.py             # ToolRegistry
│   │   ├── engine.py               # ToolEngine (validate, authorize, execute, persist)
│   │   ├── calculator.py file_search.py web_search.py code_execution.py
│   ├── search/{service.py,providers/{base.py,searxng.py,brave.py},fetcher.py}
│   ├── sandbox/client.py
│   ├── voice/{stt.py,tts.py}       # SttProvider/TtsProvider + Groq adapters (26 §2)
│   ├── documents/
│   │   ├── pipeline.py             # orchestrates extraction → chunk → embed → index
│   │   ├── extractors/{pdf.py,docx.py,text.py,markdown.py,csv.py,xlsx.py,pptx.py,base.py}
│   │   ├── normalizer.py chunker.py
│   ├── files/{storage.py,validation.py,scanner.py}
│   ├── billing/razorpay_gateway.py
│   ├── ratelimit/{limiter.py,lua/gcra.lua,policies.py,dependencies.py}
│   ├── api/
│   │   ├── deps.py                 # get_db, get_principal, require_user, require_role, require_csrf, rate_limit()
│   │   └── v1/{router.py,auth.py,users.py,models.py,conversations.py,messages.py,files.py,rag.py,
│   │          memories.py,tools.py,voice.py,usage.py,billing.py,webhooks.py,api_keys.py,
│   │          analytics.py,admin.py,health.py}
│   └── workers/
│       ├── settings.py             # WorkerSettings (functions, cron_jobs, redis settings)
│       ├── healthcheck.py          # container health: heartbeat freshness
│       └── tasks/{files.py,memory.py,summary.py,title.py,exports.py,purge.py,reaper.py,usage.py,email.py,billing.py,maintenance.py}
├── config/models.yaml              # model registry (env-interpolated)
├── alembic/{env.py,script.py.mako,versions/}
├── alembic.ini
├── tests/
│   ├── conftest.py                 # db/redis fixtures, app client, factories, fake Groq transport
│   ├── unit/ integration/ api/ security/
│   ├── perf/explain_test.py        # index-usage assertions (49 §4)
│   └── fakes/{groq_stub_server.py,embeddings.py,search_stub.py}   # test-only doubles
├── pyproject.toml  uv.lock
└── Dockerfile
```

## 4. `apps/sandbox-runner`

```
apps/sandbox-runner/
├── sandbox_runner/
│   ├── main.py            # FastAPI app: POST /v1/execute, GET /healthz
│   ├── config.py          # SANDBOX_* settings
│   ├── executor.py        # Docker Engine API calls (create/start/wait/logs/remove)
│   ├── limits.py          # resource limit constants
│   └── pool.py            # concurrency semaphore, orphan cleanup loop
├── tests/
├── pyproject.toml
└── Dockerfile
```

## 5. Rules

- One SQLAlchemy model per table; module name = singular table noun.
- Routers never import from `repositories` directly; they import services only.
- `app/ai/groq/` is the **only** package permitted to `import groq`. A Ruff banned-import rule (`flake8-tidy-imports`) enforces this.
- Test-only doubles live only in `apps/api/tests/fakes/` and `apps/web/tests/`; production code must never import them.
- Generated files (`schema.d.ts`) are committed and regenerated by `make api-types`; CI fails if stale.
