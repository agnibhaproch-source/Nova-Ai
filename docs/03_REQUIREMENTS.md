# 03 — Requirements

Requirement ID prefixes:

| Prefix | Category |
|---|---|
| FR | Functional |
| NFR | Performance |
| AVL | Availability & reliability |
| SEC | Security |
| SCL | Scalability |
| ACC | Accessibility |
| PRV | Privacy |
| MNT | Maintainability |

Keywords **MUST**, **SHOULD**, **MAY** follow RFC 2119. Each requirement names its verifying spec and test type. "Phase" refers to `53_IMPLEMENTATION_PHASES.md`.

---

## 1. Functional requirements

### 1.1 Authentication & users (Phase 1)

| ID | Requirement | Spec |
|---|---|---|
| FR-001 | Users MUST be able to sign up with email, password (12–128 chars), and display name (1–80 chars). | 09 §3 |
| FR-002 | Emails MUST be unique case-insensitively among non-deleted users. | 08 users |
| FR-003 | Users MUST be able to log in with email + password and receive an HttpOnly session cookie `nova_session`. | 09 §5 |
| FR-004 | Users MUST be able to log out, which revokes the current session server-side. | 09 §7 |
| FR-005 | Removed: no email verification step; accounts are fully usable after signup (ADR 0002). | ADR 0002 |
| FR-006 | Users MUST be able to request a password reset link valid for 60 min, single-use. | 09 §8 |
| FR-007 | Password reset and password change MUST revoke all other sessions. | 09 §8 |
| FR-008 | Users MUST be able to list active sessions (device, IP-derived approximate location omitted; IP and user agent shown) and revoke any of them. | 10 §6 |
| FR-009 | Users MUST be able to edit display name, avatar, and preferences (theme, default model, custom instructions, send-with-Enter, memory, web search, code execution toggles, locale, timezone, analytics opt-out). | 10 |
| FR-010 | Users MUST be able to delete their account with password confirmation; data is purged within 24 h. | 10 §8 |
| FR-011 | Users MUST be able to request a data export delivered as a ZIP via an expiring link. | 10 §9 |

### 1.2 Conversations & messages (Phase 2)

| ID | Requirement | Spec |
|---|---|---|
| FR-020 | Users MUST be able to create a conversation implicitly by sending the first message from `/chat`. | 11 §3 |
| FR-021 | The system MUST generate a conversation title after the first completed assistant response unless the user set one. | 11 §5 |
| FR-022 | Users MUST be able to rename, pin/unpin, archive/unarchive, delete (to trash), restore (within 30 days), and permanently delete conversations. | 11 |
| FR-023 | Users MUST be able to search their conversations by title and message text with highlighted snippets. | 11 §9 |
| FR-024 | Conversation lists MUST use cursor pagination (default 30, max 100). | 30 §6 |
| FR-025 | Assistant responses MUST stream via SSE with the event protocol in `13_STREAMING.md`. | 13 |
| FR-026 | Users MUST be able to stop a generation; partial content persists with status `cancelled`. | 13 §6 |
| FR-027 | Users MUST be able to edit a previous user message, creating a new branch. | 12 §8 |
| FR-028 | Users MUST be able to regenerate any assistant message, creating a sibling. | 12 §7 |
| FR-029 | Users MUST be able to navigate sibling branches; the selection persists (`conversations.current_leaf_message_id`). | 12 §9 |
| FR-030 | Clients MUST be able to resume an in-progress stream after reconnect using `Last-Event-ID`. | 13 §7 |
| FR-031 | Users MUST be able to give thumbs up/down feedback with optional reasons and comment. | 12 §11 |
| FR-032 | Users MUST be able to choose a model among enabled models allowed by their plan. | 15 §6 |
| FR-033 | The system MUST render GFM markdown, tables, KaTeX math, and syntax-highlighted code with copy buttons. | 27 §9 |
| FR-034 | Duplicate submissions with the same `Idempotency-Key` MUST NOT create duplicate messages or generations. | 13 §9 |

### 1.3 Files, documents, RAG (Phases 3–4)

| ID | Requirement | Spec |
|---|---|---|
| FR-040 | Users MUST be able to upload PDF, DOCX, TXT, MD, CSV, XLSX, PPTX (and PNG/JPEG/WEBP/GIF images) within plan size limits. | 18 §2 |
| FR-041 | Uploads MUST be validated by extension, declared MIME, detected magic bytes, and size before processing. | 18 §4 |
| FR-042 | Documents MUST be processed asynchronously: extraction → normalization → chunking → embedding → indexing. | 19 |
| FR-043 | Users MUST see file status (`uploading`, `processing`, `ready`, `failed`) in real time (polling ≤ 2 s interval while non-terminal). | 18 §7 |
| FR-044 | Files MUST be attachable to conversations; attached ready documents are searched automatically for each message. | 20 §3 |
| FR-045 | Answers using retrieved content MUST include citations with file name and page/sheet/slide. | 20 §8 |
| FR-046 | Users MUST be able to delete files; deletion removes the object, chunks, and embeddings. | 18 §10 |
| FR-047 | Users MUST be able to download their own files via short-lived presigned URLs. | 18 §11 |

### 1.4 Memory, tools, search, code, multimodal, voice (Phases 5–9)

| ID | Requirement | Spec |
|---|---|---|
| FR-050 | The system MAY extract long-term memories from conversations only when memory is enabled and the content meets extraction criteria. | 17 §4 |
| FR-051 | Users MUST be able to view, add, edit, delete individual memories, delete all memories, and disable memory. | 17 §8 |
| FR-052 | The model MUST only access tools registered in `ToolRegistry` and enabled for the user and plan. | 22 §3 |
| FR-053 | Tool calls and results MUST be shown in the UI and persisted in `tool_calls`. | 22 §8 |
| FR-054 | Web search results MUST be cited with title, URL, and site name. | 23 §7 |
| FR-055 | Code execution MUST occur only in the isolated sandbox runner with no network. | 24 |
| FR-056 | Image attachments MUST be sent only to models whose registry entry has `supports_vision: true`. | 25 §3 |
| FR-057 | Users MUST be able to dictate messages (STT) and, in voice mode, hear responses (TTS). | 26 |

### 1.5 Usage, billing, API keys, admin, analytics (Phases 2, 10, 11)

| ID | Requirement | Spec |
|---|---|---|
| FR-060 | Every Groq call MUST create a `usage_records` row with tokens, latency, model, status, and estimated cost. | 35 §3 |
| FR-061 | Plan quotas (messages/day, tokens/month, uploads, storage, tool calls) MUST be enforced server-side before work starts. | 35 §6 |
| FR-062 | Users MUST see their usage and remaining quota at `/settings/usage`. | 35 §8 |
| FR-063 | Users MUST be able to subscribe to `plus`/`pro` via Razorpay Subscriptions and cancel at period end. | 31 §Billing |
| FR-064 | Razorpay webhooks MUST be verified by signature and processed idempotently. | 33 §12 |
| FR-065 | Users MUST be able to create, name, list, and revoke API keys; secrets are shown once. | 10 §7 |
| FR-066 | Admins MUST have a dashboard with users, usage, cost, health, errors, subscriptions, payments, audit logs, moderation, and settings. | 36 |
| FR-067 | Admin reading of conversation *content* MUST require a stated reason and MUST be audited. | 36 §6 |
| FR-068 | Product analytics events MUST be recorded without message content. | 37 |

---

## 2. Performance requirements

| ID | Requirement | Measurement |
|---|---|---|
| NFR-001 | Time-to-first-token (browser receives first `content_delta`) p50 ≤ 800 ms, p95 ≤ 2000 ms for chat without tools/RAG, excluding Groq queueing beyond 1 s. | k6 + OTel span `chat.ttft` |
| NFR-002 | Non-streaming API endpoints p95 ≤ 300 ms, p99 ≤ 800 ms at 200 RPS per API instance. | k6 |
| NFR-003 | Conversation page initial load (LCP) ≤ 2.0 s on a mid-range phone over 4G. | Lighthouse CI |
| NFR-004 | Context building (excluding embedding call) p95 ≤ 150 ms. | span `context.build` |
| NFR-005 | RAG retrieval (embedding + vector + FTS + fusion) p95 ≤ 400 ms for a user with ≤ 50,000 chunks. | span `rag.retrieve` |
| NFR-006 | Document processing throughput ≥ 1 page/s per worker for text PDFs; a 50-page PDF ready p95 ≤ 60 s. | worker metrics |
| NFR-007 | Streaming overhead: server adds ≤ 20 ms per delta relay (Groq chunk → SSE write). | span timings |
| NFR-008 | Frontend JS for `/c/[id]` route ≤ 250 KB gzipped (excluding lazy-loaded code highlighter languages and KaTeX). | build report |
| NFR-009 | Stop generation takes effect (no more deltas rendered) ≤ 500 ms after click. | E2E test |

## 3. Availability requirements

| ID | Requirement |
|---|---|
| AVL-001 | API monthly availability ≥ 99.9% (health-checked `/readyz` from external monitor). |
| AVL-002 | Zero-downtime deployments via rolling updates; DB migrations must be backward-compatible with the previous app version (expand/contract). |
| AVL-003 | A Groq outage MUST NOT take down non-chat features; chat returns `PROVIDER_UNAVAILABLE` with retry guidance. |
| AVL-004 | A Redis outage MUST degrade gracefully: rate limiting fails **open** for authenticated users with a per-instance in-memory fallback limiter, fails **closed** for auth endpoints; streaming falls back to direct (non-resumable) streaming. |
| AVL-005 | Worker failures MUST NOT lose jobs; jobs are retried with backoff up to 5 times then marked failed with visible status. |
| AVL-006 | Generations orphaned by a crashed API instance MUST be marked `failed` with `error_code=GENERATION_INTERRUPTED` within 2 minutes (reaper job). |
| AVL-007 | RPO ≤ 5 minutes and RTO ≤ 1 hour for the primary database (`50_BACKUP_AND_RECOVERY.md`). |

## 4. Security requirements

| ID | Requirement |
|---|---|
| SEC-001 | Passwords MUST be hashed with Argon2id (m=19456 KiB, t=2, p=1 minimum) via `argon2-cffi`. |
| SEC-002 | Session tokens MUST be ≥ 256-bit random, stored only as SHA-256 hashes. |
| SEC-003 | Session cookie MUST be `HttpOnly; Secure; SameSite=Lax; Path=/` (Secure disabled only when `APP_ENV=development`). |
| SEC-004 | State-changing cookie-authenticated requests MUST pass CSRF validation (`09_AUTHENTICATION.md` §10). |
| SEC-005 | All resource access MUST verify ownership; cross-tenant access returns 404. |
| SEC-006 | Admin endpoints MUST check role server-side on every request. |
| SEC-007 | `GROQ_API_KEY` and all secrets MUST be server-only; CI MUST fail if a secret pattern is detected in the web bundle. |
| SEC-008 | All SQL MUST use SQLAlchemy parameter binding; raw string SQL concatenation is forbidden. |
| SEC-009 | Markdown rendering MUST NOT render raw HTML; links get `rel="noopener noreferrer nofollow"`. |
| SEC-010 | Outbound HTTP fetches (web page extraction) MUST go through the SSRF-safe fetcher (`33_SECURITY.md` §7). |
| SEC-011 | Code execution MUST NOT occur in the API or worker process; only in `sandbox-runner`-managed containers without network. |
| SEC-012 | Uploaded files MUST be stored under random keys, never executed, served only via presigned URLs with `Content-Disposition: attachment` for non-image types. |
| SEC-013 | API keys MUST be stored as HMAC-SHA256 hashes; plaintext shown once. |
| SEC-014 | Login MUST be rate-limited per IP and per email; accounts lock for 15 min after 10 failed attempts in 15 min. |
| SEC-015 | Audit logs MUST record auth events, admin actions, API key lifecycle, billing changes, account deletion/export. |
| SEC-016 | Retrieved documents, web content, and tool output MUST be treated as untrusted data in prompts (prompt-injection defenses in `33_SECURITY.md` §8). |
| SEC-017 | Security headers (CSP, HSTS, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, frame-ancestors 'none') MUST be set on all web responses. |
| SEC-018 | Webhook endpoints MUST verify signatures using constant-time comparison. |
| SEC-019 | Dependencies MUST be scanned in CI (pip-audit, pnpm audit, Trivy); high/critical findings block merges unless waived with an ADR. |

## 5. Scalability requirements

| ID | Requirement |
|---|---|
| SCL-001 | API and web processes MUST be stateless and horizontally scalable behind a load balancer. |
| SCL-002 | Long-running work MUST run in ARQ workers scalable independently. |
| SCL-003 | Every query on user-owned tables MUST be served by an index beginning with `user_id` or the parent foreign key. |
| SCL-004 | Database connections MUST be pooled (SQLAlchemy pool per process + PgBouncer in production at ≥ 1,000 users). |
| SCL-005 | Streaming MUST support ≥ 500 concurrent SSE connections per API instance (async I/O, no thread per connection). |
| SCL-006 | `usage_records`, `analytics_events`, and `audit_logs` MUST be designed for monthly range partitioning (introduced at the 10,000-user stage). |

## 6. Accessibility requirements

| ID | Requirement |
|---|---|
| ACC-001 | Conform to WCAG 2.2 AA. |
| ACC-002 | All interactive elements keyboard reachable with visible focus ring (2 px, `--ring` token, 2 px offset). |
| ACC-003 | Streaming message region uses `aria-live="polite"` with batched announcements (on completion, not per token). |
| ACC-004 | Color contrast ≥ 4.5:1 for text, ≥ 3:1 for UI components in both themes. |
| ACC-005 | Respect `prefers-reduced-motion`: disable non-essential animations. |
| ACC-006 | All icons-only buttons have `aria-label`; tooltips are not the only label. |
| ACC-007 | Dialogs trap focus and restore focus on close (Radix primitives). |
| ACC-008 | Touch targets ≥ 44×44 px on mobile. |

## 7. Privacy requirements

| ID | Requirement |
|---|---|
| PRV-001 | Conversation content, file content, and memories MUST NOT be sent to analytics, logs, or Sentry. |
| PRV-002 | Users MUST be able to export and delete all their data. |
| PRV-003 | Memory extraction MUST be off when the user disables memory, and MUST skip sensitive categories unless explicitly requested (`17_MEMORY_SYSTEM.md` §5). |
| PRV-004 | Admin access to content requires reason + audit (FR-067). |
| PRV-005 | Soft-deleted conversations are hard-deleted after 30 days; deleted accounts purged within 24 h; backups age out per `50_BACKUP_AND_RECOVERY.md` (≤ 35 days). |
| PRV-006 | IP addresses in `sessions`, `audit_logs` are retained ≤ 180 days then nulled by a cleanup job. |
| PRV-007 | Analytics opt-out MUST stop client and server product events for that user. |
| PRV-008 | Groq receives only the content needed for the request; user identifiers sent to Groq are limited to an opaque hashed `user` field (see `14_GROQ_INTEGRATION.md` §5.3). |

## 8. Maintainability requirements

| ID | Requirement |
|---|---|
| MNT-001 | TypeScript `strict: true`; Python `mypy --strict` on `app/` must pass. |
| MNT-002 | Lint (ESLint, Ruff) and format (Prettier, Ruff format) enforced in CI. |
| MNT-003 | Backend coverage ≥ 80% lines overall, ≥ 90% for critical modules listed in `40_TESTING.md` §9. |
| MNT-004 | Frontend types for API are generated from OpenAPI (`openapi-typescript`) — no hand-written duplicate API types. |
| MNT-005 | React components ≤ 250 lines; Python modules ≤ 500 lines; functions ≤ 60 lines (lint-warned). |
| MNT-006 | Every schema change is an Alembic migration reviewed for expand/contract compatibility. |
| MNT-007 | Every external integration sits behind a protocol/interface with a single adapter module. |
| MNT-008 | Docs updated with every architecture/API/schema change (`00_MASTER_INSTRUCTION.md` R10). |
