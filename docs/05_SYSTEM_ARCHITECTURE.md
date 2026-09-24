# 05 — System Architecture

## 1. Component overview

```
                                 ┌──────────────────────────────────────────┐
                                 │                Browser                   │
                                 │  Next.js client (React, Zustand, TanStack│
                                 │  Query, SSE parser) — never calls Groq   │
                                 └───────────────┬──────────────────────────┘
                                                 │ HTTPS (same origin: APP_URL)
                                                 ▼
                         ┌───────────────────────────────────────────────────┐
                         │                 Next.js server (web)              │
                         │  • SSR pages (app router)                          │
                         │  • BFF proxy: /api/v1/[...path] → FastAPI         │
                         │    (streams bodies, adds X-Nova-Proxy-Secret,      │
                         │     X-Forwarded-For, X-Request-ID)                 │
                         └───────────────┬───────────────────────────────────┘
                                         │ HTTP (API_INTERNAL_URL)
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                  FastAPI (api)                                          │
│ Middleware: RequestID → ProxySecret → SecurityHeaders → Logging/OTel → RateLimit(IP)    │
│ Dependencies: get_db, get_current_principal (session | api key), require_csrf, require_role│
│                                                                                         │
│  API layer (routers /api/v1/*) ──► Services ──► Repositories ──► PostgreSQL             │
│                                                                                         │
│  AuthService  UserService  ConversationService  MessageService  ChatService             │
│  ContextService  MemoryService  FileService  RagService  ToolEngine  UsageService       │
│  QuotaService  BillingService  AdminService  AnalyticsService  AuditService             │
│                                                                                         │
│  Providers/adapters (only these talk to external systems):                              │
│   GroqService → GroqProvider ─────────────────────────────────────► Groq API            │
│   EmbeddingService → TEIEmbeddingProvider ────────────────────────► embeddings (TEI)    │
│   StorageService (aioboto3) ──────────────────────────────────────► S3 / RustFS         │
│   WebSearchService → SearxngProvider | BraveProvider ─────────────► search provider     │
│   SafeFetcher (SSRF-guarded httpx) ───────────────────────────────► public web pages    │
│   SandboxClient ──────────────────────────────────────────────────► sandbox-runner      │
│   EmailSender (SMTP) ─────────────────────────────────────────────► SMTP                │
│   RazorpayGateway ────────────────────────────────────────────────► Razorpay API        │
│   GenerationBroker, RateLimiter, Cache ───────────────────────────► Redis               │
└──────────────┬──────────────────────────────┬───────────────────────────────────────────┘
               │ enqueue jobs (ARQ/Redis)      │
               ▼                               ▼
┌─────────────────────────────┐   ┌─────────────────────┐   ┌────────────────────────────┐
│  worker (ARQ, same codebase)│   │ PostgreSQL 16       │   │ Redis 7                    │
│  • process_file             │   │ + pgvector, citext, │   │ rate limits, quotas,       │
│  • extract_memories         │──►│   pg_trgm, pgcrypto │   │ gen streams, cancel flags, │
│  • summarize_conversation   │   └─────────────────────┘   │ ARQ queues, caches         │
│  • generate_title           │                             └────────────────────────────┘
│  • build_export, purge_*    │   ┌─────────────────────┐   ┌────────────────────────────┐
│  • reap_stale_generations   │──►│ S3 object storage   │   │ sandbox-runner (isolated   │
│  • aggregate_usage_daily    │   │ uploads/exports/... │   │ host) → gVisor containers, │
└─────────────────────────────┘   └─────────────────────┘   │ no network                 │
                                                            └────────────────────────────┘
Observability: every process → OTel (OTLP) traces/metrics, Sentry errors, JSON logs → stdout
```

## 2. Responsibilities

| Component | Responsibility | Must not |
|---|---|---|
| Browser app | Render UI, manage drafts/UI state, parse SSE, call `/api/v1/*` on same origin | Call Groq, hold secrets, enforce authorization |
| Next.js server | SSR, BFF proxy, security headers/CSP, static assets | Contain business logic or DB access |
| FastAPI routers | HTTP parsing, auth dependencies, calling one service method, response mapping | Contain SQL, call external APIs directly |
| Services | Business rules, transactions, authorization checks, orchestration | Build HTTP responses |
| Repositories | SQL via SQLAlchemy; every user-scoped query takes `user_id` | Business decisions |
| `ChatService` | Orchestrate a turn: validate → quota → persist user msg → create assistant msg → start generation task | Talk to Groq directly |
| `ContextService` | Build Groq message list within token budget (`16_CONTEXT_MANAGEMENT.md`) | Persist anything except cache |
| `GroqService` | Single gateway to Groq (chat, stream, tools, JSON, STT, TTS, models) | Know about HTTP requests or DB |
| `ToolEngine` | Validate/authorize/execute tool calls with timeouts | Execute unregistered functions |
| `RagService` | Retrieval + citation assembly with permission filters | Return chunks of other users |
| `GenerationBroker` | Publish/consume per-message event streams in Redis; cancellation flags | Persist messages (MessageService does) |
| Worker | Async jobs with retries | Serve HTTP |
| sandbox-runner | Run code in ephemeral hardened containers | Be reachable from the internet |

## 3. Request pipeline (every API request)

1. Next.js proxy receives `/api/v1/...`, generates `X-Request-ID` if absent (UUIDv4), forwards method, path, query, body stream, cookies, `Authorization`, `Idempotency-Key`, `Last-Event-ID`, `Content-Type`, `Accept`, and adds `X-Nova-Proxy-Secret`, `X-Forwarded-For` (client IP), `X-Forwarded-Proto`.
2. FastAPI `RequestIdMiddleware` binds `request_id` to structlog context and the OTel span.
3. `ProxySecretMiddleware` rejects requests lacking the correct secret with 404 (except `/healthz`, `/readyz`, `/api/v1/webhooks/razorpay` which Razorpay calls through the same public proxy route and therefore also carries the header — see §5.10).
4. `IpRateLimitMiddleware` applies the global per-IP limit (`34_RATE_LIMITING.md`).
5. Route dependencies resolve the principal (`09_AUTHENTICATION.md` §11), enforce CSRF for cookie-authenticated unsafe methods, check role, and apply endpoint/user/plan rate limits.
6. Router calls a service; service opens a transaction via the `UnitOfWork` (`AsyncSession`), performs authorization, and returns domain objects; router maps them to Pydantic response schemas.
7. Exceptions of type `AppError` map to the standard error envelope (`32_ERROR_HANDLING.md`).

## 4. Deployment units

| Unit | Image | Process command | Scales on |
|---|---|---|---|
| web | `apps/web/Dockerfile` (or Vercel) | `node server.js` (Next standalone) | RPS |
| api | `apps/api/Dockerfile` | `gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w $WEB_CONCURRENCY` | CPU, open SSE connections |
| worker | same image as api | `arq app.workers.settings.WorkerSettings` | queue depth |
| sandbox-runner | `apps/sandbox-runner/Dockerfile` | `uvicorn sandbox_runner.main:app` | concurrent executions |
| embeddings | TEI image | per TEI docs | embedding latency |
| postgres, redis, object storage | managed | — | — |

## 5. Data flows

### 5.1 Normal (non-streamed) chat — API key clients with `Accept: application/json`

```
Client ─POST /api/v1/conversations/{id}/messages (Accept: application/json)──► Next proxy ─► FastAPI
FastAPI: auth → rate limit → ChatService.submit_user_message()
   ├─ QuotaService.reserve()            (Redis)
   ├─ MessageRepo.insert(user msg, assistant msg[pending])   (Postgres, 1 txn)
   ├─ GenerationRunner.run(...)  awaited in-request (not detached)
   │     ContextService.build() → GroqService.stream_chat() → accumulate → tools loop
   │     MessageService.finalize()  UsageService.record()
   └─ return 200 {data: {user_message, assistant_message}}
```
Non-streamed mode uses the same runner and the same persistence; only the transport differs. Server-side timeout: 120 s.

### 5.2 Streamed chat (default)

```
Browser                 Next proxy          FastAPI (instance A)               Redis                 Groq
  │ POST messages (SSE)   │                   │                                  │                     │
  │──────────────────────►│──────────────────►│ auth, CSRF, limits, quota        │                     │
  │                       │                   │ txn: insert user msg +           │                     │
  │                       │                   │      assistant msg(status=pending)                     │
  │                       │                   │ spawn GenerationTask (asyncio)   │                     │
  │                       │                   │   ├ ContextService.build         │                     │
  │                       │                   │   ├ GroqService.stream_chat ────────────────────────► │
  │                       │                   │   │   chunks ◄──────────────────────────────────────── │
  │                       │                   │   ├ XADD gen:{msg_id} events ──►│                     │
  │                       │                   │ SSE handler: XREAD gen:{msg_id} ◄│                     │
  │◄── event: content_delta ─────────────────│                                  │                     │
  │   ...                                     │   ├ persist periodically (every 1 s / 2 KB)            │
  │◄── event: usage, message_complete ───────│   └ finalize message, usage_records, enqueue jobs      │
```
Generation is decoupled from the HTTP connection: if the client disconnects, the task continues and the client can resume (`13_STREAMING.md` §7).

### 5.3 File upload

```
Browser ─POST /files {filename,size,mime,purpose}─► FastAPI FileService.initiate
    ← {file(id,status=pending_upload), upload:{url, fields}}   (S3 presigned POST with content-length-range)
Browser ─multipart POST directly to S3 (presigned)─► S3
Browser ─POST /files/{id}/complete─► FastAPI: HEAD object (size check) → status=uploaded → enqueue process_file
Worker process_file: download → magic-byte check → ClamAV scan (if enabled) → status=processing
     → extract → normalize → chunk → embed → insert document_chunks → status=ready
Browser polls GET /files/{id} every 1.5 s until terminal status.
```

### 5.4 RAG (within a chat turn)

```
ContextService.build
  └─ RagService.retrieve(user_id, conversation_id, query)
        ├─ scope = ready files attached to conversation (+ explicit file_ids in the message)
        ├─ EmbeddingService.embed_query(query)   (Redis cache 24h)
        ├─ vector search  (pgvector HNSW, WHERE user_id = :uid AND file_id = ANY(:scope))
        ├─ full-text search (tsvector, same filters)
        ├─ Reciprocal Rank Fusion → MMR diversity → threshold → top-K within token budget
        └─ returns RetrievedChunk[] with citation metadata
  → rendered as a <retrieved_documents> system block with [n] ids
Model answers with [n] markers → StreamProcessor maps markers to citation events + message_parts(type=citation)
```

### 5.5 Tool call

```
GroqService.stream_chat(tools=registry.schemas_for(user, plan))
  → streamed tool_call deltas accumulated by index
  → finish_reason == "tool_calls"
ToolEngine.execute_all(calls):
   for each call: lookup registry → permission check (user prefs, plan, quota) → JSON-schema validate args
                → insert tool_calls(status=running) → emit SSE tool_start
                → run with timeout → persist result → emit SSE tool_result
  → append assistant(tool_calls) + tool messages to context
  → call Groq again (max 5 tool iterations per turn, then force tool_choice="none")
```

### 5.6 Web search

```
Model calls web_search{query, recency?, max_results?}
ToolEngine → WebSearchService.search(query) → Redis cache (1h) ─miss→ provider adapter (SearXNG/Brave)
   → normalize results {title,url,snippet,site_name,published_at}
   → SafeFetcher fetch top N pages (SSRF-guarded, 5s timeout, 2MB cap) → trafilatura extract → truncate
   → tool result with numbered sources → model cites [n] → citation parts (source_type=web)
```

### 5.7 Code execution

```
Model calls code_execution{language:"python", code}
ToolEngine → SandboxClient.execute(code, limits) ─HTTP (Bearer SANDBOX_RUNNER_TOKEN)─► sandbox-runner
sandbox-runner: create container (runsc, --network none, read-only rootfs, tmpfs /tmp 64MB,
                --memory 256m, --cpus 0.5, --pids-limit 64, uid 65534, cap-drop ALL, no-new-privileges)
             → write code to tmpfs → run with 10s wall timeout → capture stdout/stderr (64KB cap)
             → kill & remove container → return {exit_code, stdout, stderr, duration_ms, truncated, timed_out}
ToolEngine → tool_result (+ message_part type=code) → model continues
```

### 5.8 Authentication (login)

```
Browser ─POST /api/v1/auth/login {email,password}─► FastAPI
  rate limit (IP, email) → lookup user by citext email → check lock → argon2 verify (constant work even if user missing)
  → create session: token = 32 random bytes (base64url); store sha256(token) in sessions
  → Set-Cookie nova_session=token (HttpOnly, Secure, SameSite=Lax, Max-Age=30d)
  → Set-Cookie nova_csrf=HMAC(AUTH_SECRET, session_id) (not HttpOnly)
  → audit_logs(auth.login.succeeded) → 200 {data:{user}}
Subsequent requests: cookie → sha256 → sessions lookup (Redis cache 60s) → user → request.state.principal
```

### 5.9 Admin request

```
Browser (admin) ─GET /api/v1/admin/users?q=...─► FastAPI
  principal resolved → require_role("admin" | "support" per endpoint) → AdminService
  → queries (metadata only) → response
Mutations (suspend, role change, settings) → same txn writes audit_logs(actor, action, target, reason)
Content access (GET /admin/conversations/{id}/messages?reason=...) → admin only, reason required, audited
```

### 5.10 Payment webhook

```
Razorpay ─POST https://APP_URL/api/v1/webhooks/razorpay─► Next proxy ─► FastAPI
  verify X-Razorpay-Signature over raw body (HMAC-SHA256, RAZORPAY_WEBHOOK_SECRET)
  → insert payment_webhook_events (unique event id) → if duplicate: 200 no-op
  → BillingService.apply_event() in txn → update subscriptions/payments/users.plan_key → 200
```

## 6. Background job catalogue (ARQ)

| Job | Queue | Trigger | Spec |
|---|---|---|---|
| `send_email` | default | after-commit (password reset, export ready, quota warning) | 09, 10, 35 |
| `generate_title` | default | first assistant completion | 11 §5 |
| `summarize_conversation` | default | context threshold | 16 §6 |
| `extract_memories` | default | message completion + pre-filter | 17 §4 |
| `process_file` | files | upload complete / retry | 18, 19 |
| `reprocess_files`, `reembed` | files_low | admin/system | 19 §9, 21 §9 |
| `build_export` | exports | user request | 10 §9 |
| `purge_user`, `purge_file` | default | deletion | 10 §8, 18 §10 |
| `reap_stale_generations` | cron (30 s) | — | 12 §4 |
| `aggregate_usage_daily` | cron (5 min) | — | 35 §4 |
| `reconcile_quotas` | cron (daily) | — | 35 §6 |
| `requeue_stuck_files` | cron (5 min) | — | 48 §5 |
| `purge_empty_conversations` | cron (hourly) | — | 11 §3 |
| `purge_trashed_conversations`, `purge_deleted_users`, `purge_deleted_files`, `purge_expired_sessions`, `null_old_ips`, `purge_old_analytics`, `purge_soft_deleted_memories`, `expire_data_exports` | cron | — | 07 §13 |
| `decay_memories` | cron (nightly) | — | 17 §6 |
| `sync_subscriptions` | cron (hourly) | — | 48 §7 F15 |
| `downgrade_halted_subscriptions` | cron (hourly) | halted > 3 days | 31 §12 |
| `export_business_metrics` | cron (5 min) | — | 39 §4 |
| `ensure_partitions` | cron (daily, Phase 11) | — | 49 §4 |

Cron jobs run on a single leader (ARQ unique job ids + Redis lock). All jobs are idempotent and carry `traceparent`.

## 7. Cross-cutting concerns

- **Transactions:** one `AsyncSession` per request via dependency; services use `async with uow.begin()`. The generation task uses its own sessions (short transactions per persistence checkpoint).
- **Background jobs:** enqueued **after** commit via `uow.after_commit(enqueue(...))` hooks to avoid jobs referencing uncommitted rows.
- **Caching:** Redis only; every cache key is namespaced `nova:{env}:...` and has a TTL.
- **Time:** all timestamps UTC (`timestamptz`), ISO-8601 with `Z` in API.
- **IDs:** UUIDv4 generated in the DB (`gen_random_uuid()`), exposed as strings.
- **Observability:** OTel trace context propagated web → api → worker (job metadata carries `traceparent`) → sandbox-runner.
