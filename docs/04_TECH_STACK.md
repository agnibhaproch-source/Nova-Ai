# 04 — Technology Stack

This stack is fixed (`00_MASTER_INSTRUCTION.md` R6). Versions: use the latest stable release of each listed major at project start and pin exact versions in lockfiles (`pnpm-lock.yaml`, `uv.lock`). Minimum majors are given where they matter.

Format for each entry: **Why / What / Where / Must NOT be used for / Alternatives considered**.

---

## 1. Runtimes and package management

### Node.js ≥ 22 LTS + pnpm ≥ 9
- **Why:** LTS runtime for Next.js; pnpm gives fast, strict, disk-efficient installs and workspaces.
- **Where:** `apps/web`, root tooling. `pnpm-workspace.yaml` at root.
- **Not for:** backend business logic.
- **Alternatives:** npm (slower, less strict), yarn berry (PnP friction), Bun (runtime compatibility risk with Next.js tooling).

### Python 3.12 + uv
- **Why:** mature async ecosystem, strong typing support; `uv` is a fast resolver/lockfile manager.
- **Where:** `apps/api`, `apps/sandbox-runner`, `evals/`.
- **Not for:** executing user code (that is the sandbox's job).
- **Alternatives:** Poetry (slower), pip-tools (no workspace ergonomics).

## 2. Frontend

### Next.js (App Router, ≥ 15) + React (≥ 19) + TypeScript (strict)
- **Why:** SSR/streaming, route handlers for the BFF proxy, file-based routing, image/font optimization, first-class Vercel deployment.
- **What:** renders all pages; hosts `app/api/v1/[...path]/route.ts`, the **BFF proxy** that forwards API calls (including SSE) to FastAPI with the proxy secret header.
- **Where:** `apps/web`.
- **Not for:** business logic, database access, calling Groq, storing secrets other than `API_PROXY_SHARED_SECRET` and `API_INTERNAL_URL` (server-only). Next.js Server Actions are **not used** (single API contract through FastAPI).
- **Alternatives:** Vite SPA (no SSR, needs separate proxy), Remix (smaller ecosystem for our UI libs).

### Tailwind CSS (≥ 4)
- **Why:** utility-first styling with design tokens via CSS variables; consistent spacing/typography.
- **Where:** all styling in `apps/web`. Tokens in `src/styles/globals.css`.
- **Not for:** inline style objects (except dynamic values such as virtualized row heights).
- **Alternatives:** CSS Modules (less consistency), styled-components (runtime cost).

### shadcn/ui + Radix UI
- **Why:** accessible primitives (Radix) with owned, editable component source (shadcn) — no black-box design system.
- **Where:** `apps/web/src/components/ui/*` (generated shadcn components; editable).
- **Not for:** feature logic inside `ui/` components.
- **Alternatives:** MUI (heavy, opinionated look), Chakra (runtime CSS-in-JS).

### Framer Motion (package `motion`)
- **Why:** declarative, interruptible animations (sidebar, dialogs, message entrance).
- **Where:** feature components needing motion; wrapped by `useReducedMotion`.
- **Not for:** per-token streaming animation (performance), layout-critical rendering.
- **Alternatives:** CSS transitions only (insufficient for presence animations).

### Lucide React
- **Why:** consistent, tree-shakeable icon set. **Where:** all icons. **Not for:** brand logos (NOVA logo is a local SVG). **Alternatives:** Heroicons.

### Zustand
- **Why:** minimal client state for UI and live streaming state without prop drilling.
- **Where:** `src/stores/` — `ui-store` (sidebar, dialogs), `composer-store` (drafts per conversation), `stream-store` (active generations).
- **Not for:** server data caching (TanStack Query owns that), auth truth.
- **Alternatives:** Redux Toolkit (boilerplate), Jotai (fine, but team standardizes on Zustand).

### TanStack Query (v5)
- **Why:** server-state caching, invalidation, pagination (`useInfiniteQuery`), retries.
- **Where:** `src/features/*/api/*.ts` hooks.
- **Not for:** SSE streams (handled by `src/lib/sse/`), purely local UI state.
- **Alternatives:** SWR (fewer mutation features).

### Supporting frontend libraries
| Library | Purpose | Not for |
|---|---|---|
| `openapi-typescript` + `openapi-fetch` | Generated API types and typed fetch client | Hand-written API types |
| `zod` + `react-hook-form` + `@hookform/resolvers` | Form validation | Replacing server validation |
| `react-markdown` + `remark-gfm` + `remark-math` + `rehype-katex` + `katex` | Markdown/math rendering (no raw HTML) | Rendering untrusted HTML (`rehype-raw` is **forbidden**) |
| `shiki` | Syntax highlighting (lazy-loaded languages, run in a Web Worker for blocks > 200 lines) | Server-side highlighting of whole conversations |
| `@tanstack/react-virtual` | Virtualized sidebar and long message lists | — |
| `sonner` | Toasts | Critical errors needing action (use inline alerts) |
| `date-fns` | Date formatting/grouping | — |
| `@sentry/nextjs` | Frontend error reporting | Sending message content |
| `recharts` | Admin & usage charts | — |
| `cmdk` (via shadcn `Command`) | Command palette | — |
| `class-variance-authority`, `clsx`, `tailwind-merge` | Variant styling, `cn()` | — |
| `pino` | Next.js server JSON logs | Browser logging |
| `msw` | Frontend tests only | Production code |

## 3. Backend

### FastAPI
- **Why:** async-first, Pydantic integration, OpenAPI generation, dependency injection.
- **Where:** `apps/api/app/main.py`, routers in `app/api/v1/`.
- **Not for:** long-running jobs inside request handlers (except the generation task, which is bounded and tracked; see `13_STREAMING.md`), running user code.
- **Alternatives:** Django (sync-heavy ORM), Litestar (smaller ecosystem).

### Pydantic v2 + pydantic-settings
- **Why:** request/response validation, typed settings from env.
- **Where:** `app/schemas/*`, `app/core/config.py` (`Settings`).
- **Not for:** ORM models.

### SQLAlchemy 2.x (async, `asyncpg` driver)
- **Why:** mature ORM with typed `Mapped[]` models, async sessions, explicit transactions.
- **Where:** `app/models/*`, `app/repositories/*`.
- **Not for:** string-concatenated SQL. `text()` only with bound parameters and only inside repositories.
- **Alternatives:** SQLModel (thin, less control), Tortoise (less mature).

### Alembic
- **Why:** versioned migrations. **Where:** `apps/api/alembic/`. **Not for:** data backfills over 100k rows (use worker jobs). **Alternatives:** none serious for SQLAlchemy.

### ARQ (async Redis queue)
- **Why:** asyncio-native job queue on the Redis we already run; supports retries, deferred jobs, cron.
- **Where:** `app/workers/` — run with `arq app.workers.settings.WorkerSettings`.
- **Not for:** real-time streaming delivery (Redis Streams via `GenerationBroker`).
- **Alternatives:** Celery (sync-first, heavier), Dramatiq (no native asyncio), RQ (sync).

### Other backend libraries
| Library | Purpose |
|---|---|
| `groq` (official SDK) | **Only** LLM/STT/TTS client (`AsyncGroq`) |
| `httpx` | Outbound HTTP (embeddings server, search providers, sandbox runner, SSRF-safe fetcher) |
| `argon2-cffi` | Password hashing |
| `redis` (redis-py asyncio) | Rate limiting, caches, streams, locks |
| `aioboto3` | S3-compatible storage |
| `python-magic` (libmagic) | Content-type detection by magic bytes |
| `pypdf` | PDF text extraction (BSD license) |
| `python-docx`, `openpyxl`, `python-pptx` | Office extraction |
| `trafilatura` | Web page main-content extraction |
| `pgvector` (Python) | SQLAlchemy `Vector` type |
| `structlog` | Structured JSON logging |
| `opentelemetry-*` | Tracing/metrics (FastAPI, SQLAlchemy, httpx, redis instrumentations) |
| `sentry-sdk` | Error reporting |
| `razorpay` (official SDK) | Razorpay API calls |
| `pyyaml` | Model registry file |
| `email-validator` | Email validation |
| `user-agents` | Parse user agent for session device labels |
| `jinja2` | Prompt templates (`app/ai/prompts/*.md`) |
| `Pillow` | Image validation, EXIF stripping, derivatives |
| `aiosmtplib` | SMTP email sending |
| `charset-normalizer` | Text encoding detection for TXT/MD/CSV |
| `cachetools` | In-process fallback rate limiter |
| `gunicorn` + `uvicorn` | Production ASGI serving |
| `docker` (Docker SDK for Python) | sandbox-runner only |
| `pytest`, `pytest-asyncio`, `pytest-xdist`, `pytest-cov`, `respx`, `freezegun` | Tests only |

Prohibited dependencies: `openai`, `anthropic`, `google-generativeai`/`google-genai`, `mistralai`, `cohere`, `together`, `litellm`, `langchain-*` provider packages, `llama-index` LLM integrations, `pymupdf` (AGPL). CI enforces this list (`46_CI_CD.md` §4).

## 4. Data

### PostgreSQL 16 + pgvector (≥ 0.7)
- **Why:** relational integrity, JSONB, full-text search, and vector similarity in one ACID store.
- **Extensions:** `vector`, `citext`, `pg_trgm`, `pgcrypto`.
- **Where:** all durable data (`08_DATABASE_SCHEMA.md`).
- **Not for:** blobs (files go to S3), ephemeral counters (Redis).
- **Alternatives:** dedicated vector DB (extra system, consistency/authorization duplication), MySQL (weaker FTS/JSON/vector).

### Redis 7
- **Why:** low-latency ephemeral state.
- **Uses:** rate limiting (Lua GCRA), quota counters, generation streams (Redis Streams), cancellation flags, ARQ queue, caches (search results, embeddings of queries, model registry health), distributed locks.
- **Not for:** source-of-truth data. Everything in Redis must be reconstructible or safely lost.
- **Alternatives:** Memcached (no streams/Lua), Postgres-only (too slow for per-request limits).

### S3-compatible object storage
- **Why:** durable, cheap, scalable blob storage with presigned URLs.
- **Where:** uploads, avatars, data exports, audio. Dev: RustFS (S3-compatible; ADR 0003). Prod: AWS S3 (reference) or Cloudflare R2.
- **Not for:** serving public static assets of the app (Next.js/Vercel does that).

## 5. AI

### Groq API (sole LLM provider)
- **Why:** very low latency inference; OpenAI-compatible chat schema with tool calling; audio transcription and speech endpoints.
- **What:** chat completions (streaming + tools + JSON mode), audio transcription (STT), speech synthesis (TTS), model listing.
- **Where:** exclusively `app/ai/groq/` via `GroqService`.
- **Not for:** embeddings (Groq embeddings are not assumed; embeddings use `EmbeddingProvider`, see below).
- **Alternatives:** none permitted (product requirement).

### Embeddings: self-hosted open-weights embedding model via Text Embeddings Inference (TEI)
- **Why:** RAG and memory need embeddings; must not use a prohibited hosted LLM vendor; self-hosting keeps data private.
- **What:** `EmbeddingProvider` protocol with adapter `TEIEmbeddingProvider` (HTTP `POST {EMBEDDING_ENDPOINT}/embed`). The operator selects the model (`EMBEDDING_MODEL`) and its dimension (`EMBEDDING_DIMENSIONS`). No specific model is mandated by these docs.
- **Where:** `app/embeddings/`; `embeddings` service in Docker Compose.
- **Not for:** generating answers.
- **Alternatives:** in-process sentence-transformers (bloats API/worker memory; rejected), hosted embedding APIs from prohibited vendors (rejected).

## 6. Tools infrastructure

| Tech | Why | Where | Not for |
|---|---|---|---|
| SearXNG (self-hosted) — default web search adapter | Provider-agnostic meta-search, no per-query fees | `searxng` compose service; `app/search/providers/searxng.py` | Scraping at scale |
| Brave Search API — alternate adapter | Reliable hosted search API | `app/search/providers/brave.py` | — |
| gVisor (`runsc`) + Docker Engine | Kernel-level isolation for untrusted code | `apps/sandbox-runner` on isolated hosts | Running on the API host |
| ClamAV (`clamd`) | Malware scanning of uploads (optional, on in production) | `clamav` service; `app/files/scanner.py` | — |

## 7. Streaming

**Server-Sent Events (SSE)** over HTTP/1.1 or HTTP/2. **Why:** one-directional token streaming, proxies well, simple reconnection semantics. **Where:** message create/regenerate/edit/resume endpoints. **Not for:** client→server messages (plain HTTP POST). **Alternatives:** WebSockets (stateful, harder to scale/proxy; reconsider only for full-duplex voice, see `26_VOICE_SYSTEM.md` §8).

## 8. Containers, CI/CD

- **Docker + Docker Compose v2:** reproducible dev (`43_DOCKER.md`); production images built once, promoted across environments.
- **GitHub Actions:** CI/CD (`46_CI_CD.md`). Not for storing secrets outside GitHub Environments.

## 9. Testing

| Tool | Scope |
|---|---|
| pytest + pytest-asyncio + HTTPX (`AsyncClient` with `ASGITransport`) | Backend unit/integration/API tests |
| Vitest + React Testing Library + MSW | Frontend unit/component tests (MSW only in tests) |
| Playwright | E2E across Chromium, WebKit, mobile viewport |
| k6 | Load tests including SSE |
| axe-core (`@axe-core/playwright`) | Accessibility checks |

## 10. Observability

- **OpenTelemetry** (traces + metrics, OTLP exporter) → any OTLP backend (reference: Grafana Cloud / self-hosted Tempo+Prometheus+Loki). Not for log content with PII.
- **Sentry** for exceptions (web + api + worker) with PII scrubbing.
- **structlog** JSON logs to stdout; the platform ships them.

## 11. Payments

**Razorpay** (Subscriptions + Checkout.js + webhooks) for India-focused billing in INR. Server uses the official `razorpay` Python SDK; browser loads `https://checkout.razorpay.com/v1/checkout.js` only on the billing page. Not for storing card data (never touches our servers).

## 12. Email

SMTP via `aiosmtplib` behind `EmailSender` protocol. Dev: Mailpit. Prod: any SMTP-capable transactional provider (reference: Amazon SES SMTP). Not for marketing email.
