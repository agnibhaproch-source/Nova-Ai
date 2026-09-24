# 02 — Product Requirements Document (PRD)

Owner: Product + Principal Architect. Normative detail lives in the subsystem documents referenced in each section; this PRD defines *what* and *why*.

---

## 1. Personas

### P1 — Priya, product analyst (knowledge worker)
- 29, Bengaluru. Uses AI daily for summarizing reports and drafting emails.
- Needs: fast answers, uploading PDFs/XLSX, citations she can verify, history she can search.
- Frustrations: hallucinated numbers, losing old chats, slow tools.

### P2 — Arjun, backend developer
- 26, Pune. Debugging, learning new libraries, quick scripts.
- Needs: excellent code rendering, copy buttons, running Python snippets, editing prompts and regenerating.
- Frustrations: broken markdown, no syntax highlighting, tools that silently fail.

### P3 — Meera, postgraduate student
- 23, Delhi. Research and study.
- Needs: document Q&A with page citations, web search for recent papers, affordable plan, mobile use.
- Frustrations: price, mobile UX, no sources.

### P4 — Sam, indie builder (API user)
- Wants a hosted assistant with an API key, usage visibility, and hard spending limits.

### P5 — Ops admin (internal)
- Monitors health, costs, abuse; handles support requests (suspend users, revoke sessions, check payments). Must not casually read user conversations.

## 2. User journeys

### J1 — Sign up and first chat
1. Lands on `/` → clicks **Get started**.
2. `/signup`: display name, email, password (strength meter) → submit.
3. The user is logged in and can use everything immediately; there is no email verification step (ADR 0002).
4. `/onboarding`: 2 steps (what do you use Nova for → optional custom instructions; memory on/off explained). Skippable.
5. `/chat` empty state (logo and greeting) → types a question → presses Enter.
6. Conversation created, URL changes to `/c/{id}`, response streams, title appears in sidebar after the first response.

### J2 — Returning user continues work
1. Opens app → session cookie valid → sidebar shows conversations grouped Today / Yesterday / Previous 7 days / Previous 30 days / by month.
2. `Ctrl/Cmd+K` → searches "quarterly revenue" → opens matching conversation scrolled to the matching message.

### J3 — Document Q&A
1. In a conversation, clicks paperclip or drags a PDF onto the composer.
2. Chip shows upload progress → "Processing…" → "Ready" (typically < 30 s for 50 pages).
3. Asks "What were the risks listed in section 4?" → answer streams with inline citation markers `[1]`, `[2]` → hovering shows file name + page → clicking opens the source panel with the excerpt.

### J4 — Edit and regenerate
1. Hovers own earlier message → **Edit** → modifies text → **Save & submit**.
2. A new branch is created; `< 2/2 >` navigator appears on the message; the old branch remains accessible.
3. On an assistant message → **Regenerate** → new sibling response; navigator `< 2/2 >`.

### J5 — Stop generation
1. While streaming, clicks **Stop** (or presses `Esc` with focus in the composer).
2. Streaming halts within 500 ms; partial answer persists with status "Stopped".

### J6 — Web search
1. Asks "What's the latest stable Python release?" with web search enabled.
2. UI shows a tool activity row "Searching the web: latest stable Python release" → sources appear → answer cites them.

### J7 — Code execution
1. Asks "Compute the IRR of these cash flows".
2. Model calls `code_execution`; UI shows collapsible "Ran Python" block with code, stdout, and exit status; answer uses the output.

### J8 — Memory
1. Says "I'm vegetarian, remember that for recipes."
2. Toast: "Memory updated" with **Manage** link. Settings → Personalization lists the memory; user can edit/delete or turn memory off.

### J9 — Upgrade
1. Hits daily limit → inline banner "You've reached today's limit on Free. Upgrade for more."
2. `/settings/billing` → selects Plus → Razorpay Checkout → success → plan badge updates immediately after server-side signature verification; webhooks keep state consistent.

### J10 — API key usage
1. `/settings/api-keys` → **Create key** → name it → secret shown once → copy.
2. Calls `POST /api/v1/conversations/{id}/messages` with `Authorization: Bearer nova_sk_...` and receives SSE.

### J11 — Data control
1. Settings → Data controls → **Export data** → receives email with a 24-hour download link to a ZIP.
2. **Delete account** → confirms with password and typing "DELETE" → logged out; data purged within 24 h.

### J12 — Admin handles abuse
1. Admin sees spike in rate-limit events for a user → opens user → views usage and moderation flags (metadata only) → suspends user with reason → all sessions revoked; action audited.

## 3. Feature requirements (summary; IDs map to `03_REQUIREMENTS.md`)

| Area | Feature | Priority | Spec |
|---|---|---|---|
| Auth | Email/password signup, login, logout, verification, reset, sessions | MVP | 09 |
| User | Profile, preferences, custom instructions, sessions list, delete, export | MVP (export: post-MVP) | 10 |
| Chat | Create, list, rename, pin, archive, delete, restore, search | MVP | 11 |
| Messages | Streaming, stop, edit (branch), regenerate, copy, feedback | MVP | 12, 13 |
| Rendering | Markdown (GFM), tables, LaTeX math, syntax highlighting, copy code | MVP | 27 |
| Models | Model picker from configured Groq models | MVP | 15 |
| Files | Upload, list, delete, attach to conversation | MVP | 18 |
| Documents | Extraction for PDF, DOCX, TXT, MD, CSV, XLSX, PPTX | MVP | 19 |
| RAG | Retrieval with citations over attached files and user library | MVP | 20, 21 |
| Usage | Token/request tracking, quotas, usage page | MVP | 35 |
| Rate limiting | IP/user/endpoint/API key/plan | MVP | 34 |
| Admin | Users, usage, health, audit logs | MVP (basic), full post-MVP | 36 |
| Memory | Extraction, management UI, toggle | Post-MVP | 17 |
| Tools | Calculator, file search | Post-MVP | 22 |
| Web search | Search tool + citations | Post-MVP | 23 |
| Code execution | Python sandbox | Post-MVP | 24 |
| Images | Image input to vision-capable models | Post-MVP | 25 |
| Voice | STT dictation, voice mode with TTS | Post-MVP | 26 |
| Billing | Plans, Razorpay subscriptions, invoices list | Post-MVP | 31, 35 |
| API keys | Personal API keys with scopes | Post-MVP | 10, 31 |
| Analytics | First-party product analytics | Post-MVP | 37 |
| Future | Projects, sharing, team workspaces, video | Future | 52 |

## 4. Functional requirements (product level)

1. Users can only ever see their own conversations, messages, files, memories, API keys, usage, and billing records.
2. Every assistant response is persisted, including partial responses from stopped or failed generations (with the corresponding status).
3. The first assistant response in a conversation triggers automatic title generation (≤ 60 characters) unless the user already renamed it.
4. Conversations are ordered by last activity; pinned conversations appear first.
5. The composer supports multi-line input, attachments, model selection, tool toggles (web search, code execution when enabled for the plan), and voice dictation.
6. Answers that used files or web pages show numbered citations linked to sources.
7. Regeneration and edits create branches; the user can navigate between sibling versions.
8. Users see remaining quota and receive clear messages when limits are hit.
9. Admins can manage users, see usage and costs, view health, audit logs, payments, subscriptions, moderation flags, and system settings.

## 5. Non-functional requirements (product level)

- **Latency:** p50 TTFT ≤ 800 ms, p95 ≤ 2 s (plain chat, excluding tool/RAG time). Sidebar and conversation load p95 ≤ 400 ms API time.
- **Availability:** 99.9% monthly for API (excluding upstream Groq outages, during which the UI shows a clear provider error).
- **Security:** OWASP ASVS Level 2 aligned (see `33_SECURITY.md`).
- **Privacy:** no conversation content in analytics or logs by default; user-controlled deletion.
- **Accessibility:** WCAG 2.2 AA.
- **Responsiveness:** fully usable from 360 px width upward.
- **Scalability:** architecture supports 100,000+ registered users with horizontal scaling (`49_SCALABILITY.md`).

## 6. MVP definition

MVP = Implementation Phases **1–4** (`53_IMPLEMENTATION_PHASES.md`):

- Auth (signup, login, logout, verification, password reset, sessions list/revoke)
- Profile + preferences + custom instructions
- Conversations CRUD, search, archive, trash/restore
- Streaming chat through Groq with stop, edit, regenerate, feedback
- Markdown/code rendering
- Model picker (configured Groq models)
- Rate limiting and usage tracking with Free-plan quotas
- File upload + document processing + RAG with citations
- Basic admin: dashboard, users, usage, health, audit logs
- Docker Compose local environment, CI pipeline, staging deployment

## 7. Post-MVP (Phases 5–11)

Memory (5), tool framework + calculator + file search (6), web search (7), code execution (8), voice + image input (9), billing + API keys + analytics (10), production scaling hardening + full admin (11).

## 8. Future functionality (not scheduled)

Projects/folders, conversation sharing via read-only links, team workspaces, custom assistants with saved instructions, scheduled tasks, video input, native mobile apps, additional locales.

## 9. Acceptance criteria (product level)

| ID | Criterion |
|---|---|
| AC-01 | A new user can sign up and receive a streamed answer within 2 minutes of landing, on desktop and on a 360 px mobile viewport. |
| AC-02 | Refreshing the page mid-stream resumes the same response without duplicated text (`13_STREAMING.md` §7). |
| AC-03 | Pressing Stop halts token rendering within 500 ms and the partial message is persisted with status `cancelled`. |
| AC-04 | Editing a user message creates a new branch; both branches remain navigable after reload. |
| AC-05 | A 50-page text PDF becomes `ready` within 60 s (p95) and questions about it return answers with at least one correct page citation in the evaluation suite (`41_AI_EVALUATION.md`). |
| AC-06 | User A can never retrieve User B's conversation, message, file, chunk, or memory via any endpoint (automated authz test suite passes). |
| AC-07 | No request from the browser goes to a Groq domain (verified by Playwright network assertion). |
| AC-08 | Exceeding a quota returns `429 QUOTA_EXCEEDED` or `RATE_LIMITED` with `Retry-After`, and the UI shows the correct upgrade/wait message. |
| AC-09 | Admin endpoints return `403 FORBIDDEN` for non-admins; every admin mutation creates an `audit_logs` row. |
| AC-10 | Successful Razorpay subscription activates the plan within 5 s of checkout success and is reconciled by webhook. |
| AC-11 | Data export ZIP contains all conversations, messages, memories, and file metadata for the user and nothing belonging to others. |
| AC-12 | Lighthouse accessibility score ≥ 95 on landing, login, and chat pages; axe-core reports zero serious/critical violations. |
