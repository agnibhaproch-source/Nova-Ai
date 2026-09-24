# 00 — Master Instruction

> **Audience:** every human engineer and every AI coding agent (Claude, Codex, etc.) that implements, modifies, reviews, or deploys NOVA AI.
> **Status:** Normative. This file overrides every other document when a conflict is not otherwise resolved by §4.

---

## 1. What this documentation is

The `docs/` directory is the **single source of truth** for NOVA AI, a production-grade, ChatGPT-like conversational AI platform whose language model inference is provided **exclusively by Groq**.

The documentation specifies product behavior, architecture, data model, API contract, UI, security, operations, and the phased build plan. Code must conform to the documentation. When code and documentation disagree, the code is wrong unless the documentation is deliberately updated in the same change (see §6).

## 2. Mandatory reading order

Before any **major implementation** (a new phase, a new subsystem, a schema change, a new external dependency, or any change touching more than one service), read **all** `docs/*.md` files. For small, localized changes, read at minimum:

1. `00_MASTER_INSTRUCTION.md` (this file)
2. `55_AI_CODING_RULES.md`
3. `54_CODING_STANDARDS.md`
4. `56_DEFINITION_OF_DONE.md`
5. Every document whose subject the change touches (use the index in §8).

Recommended full reading order for a fresh agent:

```
00 → 01 → 02 → 03 → 04 → 05 → 06 → 53 → 55 → 54 → 56
then the subsystem docs in numeric order (07–51), then 52.
```

## 3. Non-negotiable rules

| # | Rule | Detail |
|---|------|--------|
| R1 | **Groq is the only LLM provider.** | Every LLM-generated token (chat answers, titles, summaries, memory extraction, evaluation judging, speech-to-text, text-to-speech) comes from the Groq API through `GroqService` (`apps/api/app/ai/groq/service.py`). Do **not** add OpenAI, Anthropic, Google Gemini, OpenRouter, Together AI, Mistral API, Cohere, Fireworks, Replicate, Azure OpenAI, AWS Bedrock, Ollama-as-a-provider, or any other hosted LLM. Do not install their SDKs. The `groq` Python SDK is the only LLM SDK permitted. |
| R2 | **The browser never calls Groq.** | Flow is always `Browser → Next.js (BFF proxy) → FastAPI → ChatService → ContextService → GroqService → Groq API`. `GROQ_API_KEY` exists only in the API and worker processes. It must never appear in `apps/web`, in any `NEXT_PUBLIC_*` variable, in logs, in error messages, or in client bundles. |
| R3 | **Never expose secrets.** | No secret in source, git history, logs, analytics, Sentry events, API responses, Docker images, or test fixtures. Use `.env` (git-ignored) locally and a secret manager in deployed environments. See `33_SECURITY.md` §9 and `42_ENVIRONMENT_VARIABLES.md`. |
| R4 | **No fake production functionality.** | Never ship stubbed, mocked, hard-coded, or "simulated" behavior in production code paths (e.g., fake streaming, canned AI responses, pretend payments, placeholder search results). Test doubles live only under `tests/` directories or behind `APP_ENV=test` guards that are refused at startup in `production`/`staging` (see `40_TESTING.md` §4). If a feature cannot be implemented yet, it must be **absent or disabled with an explicit, user-visible "not available" state**, never faked. |
| R5 | **Do not bypass the architecture.** | Routers call services; services call repositories and providers; only `GroqService` talks to Groq; only `StorageService` talks to S3; only `SandboxClient` talks to the sandbox runner; only `EmbeddingService` produces embeddings; only `WebSearchService` talks to search providers. No SQL in routers. No business logic in React presentational components. |
| R6 | **Do not change technologies casually.** | The stack in `04_TECH_STACK.md` is fixed. Adding or replacing a technology requires an Architecture Decision Record (ADR) in `docs/adr/NNNN-title.md` plus updates to `04_TECH_STACK.md` and any affected docs, in the same pull request. |
| R7 | **Preserve working code.** | Do not rewrite, reformat, or restructure working code that is outside the scope of the task. Refactors are separate, explicitly scoped changes. |
| R8 | **Implement features end-to-end.** | A feature is only complete when database, backend, API, frontend, authorization, error handling, tests, and docs all exist and pass (`56_DEFINITION_OF_DONE.md`). |
| R9 | **Test after implementation.** | Run the relevant test suites, linters, type checkers, and builds after every meaningful change (`44_LOCAL_DEVELOPMENT.md` §8). Never disable, skip, or weaken a test to make it pass. |
| R10 | **Keep documentation synchronized.** | Any change to architecture, schema, API contracts, environment variables, events, or error codes must update the corresponding documents in the same change. |
| R11 | **Never invent model IDs or external APIs.** | Groq model identifiers, context windows, output limits, and prices are supplied by operators from current Groq documentation via configuration (`15_MODEL_CONFIGURATION.md`). Third-party API shapes (Groq, Razorpay, search providers) must be verified against official documentation/SDK source before implementation. |
| R12 | **Authorization on every resource.** | Every read or write of a user-owned resource (conversation, message, file, chunk, memory, API key, subscription, export, feedback) verifies ownership server-side. Missing or foreign resources return `404 RESOURCE_NOT_FOUND` (never leak existence). |

## 4. Documentation priority and conflict resolution

When two documents disagree, resolve in this order (highest wins):

1. `00_MASTER_INSTRUCTION.md`
2. `33_SECURITY.md` (security requirements always win over convenience)
3. `08_DATABASE_SCHEMA.md` (data model) and `31_API_ENDPOINTS.md` (wire contract)
4. `14_GROQ_INTEGRATION.md`, `13_STREAMING.md`, `16_CONTEXT_MANAGEMENT.md`
5. `05_SYSTEM_ARCHITECTURE.md` and `06_FOLDER_STRUCTURE.md`
6. `03_REQUIREMENTS.md`
7. Other subsystem documents (`09`–`51`)
8. `02_PRD.md`, `01_PROJECT_VISION.md`, `52_ROADMAP.md`
9. `README.md`, `CLAUDE.md`, `AGENTS.md` (summaries only; never authoritative)

Procedure when a conflict is discovered:

1. Apply the higher-priority document.
2. Fix the lower-priority document in the same change.
3. If the conflict cannot be resolved by priority (e.g., two same-level docs, or the higher-priority doc is clearly wrong), make the **smallest architecture-consistent decision**, record it in `docs/adr/`, update both documents, and call it out in the pull request description.
4. Never silently diverge.

## 5. Canonical names (glossary)

Use these names exactly in code, docs, logs, and UI copy.

| Concept | Canonical name |
|---|---|
| Product | NOVA AI (UI short name: "Nova") |
| Monorepo root | `nova-ai/` |
| Frontend app | `apps/web` (Next.js App Router) |
| Backend API | `apps/api` (FastAPI), Python package `app` |
| Background worker | `apps/api` package `app.workers`, run as the `worker` process (ARQ) |
| Code sandbox service | `apps/sandbox-runner` |
| LLM provider abstraction | `LLMProvider` protocol, sole implementation `GroqProvider`, facade `GroqService` |
| Model registry | `ModelRegistry`, loaded from `apps/api/config/models.yaml` |
| Model alias used by the app | `model_key` (e.g., `primary`, `fast`, `vision`) |
| Actual Groq identifier | `groq_model_id` (from env; never hard-coded) |
| Embedding abstraction | `EmbeddingProvider` / `EmbeddingService` |
| Context builder | `ContextService` |
| Streaming broker | `GenerationBroker` (Redis Streams) |
| Session cookie | `nova_session` |
| CSRF cookie / header | `nova_csrf` / `X-CSRF-Token` |
| API key prefix | `nova_sk_` |
| Proxy auth header (web→api) | `X-Nova-Proxy-Secret` |
| Request ID header | `X-Request-ID` |
| API base path | `/api/v1` |
| SSE event names | `message_start`, `message_snapshot`, `content_delta`, `tool_start`, `tool_result`, `citation`, `usage`, `conversation_updated`, `message_complete`, `error` |
| Plans | `free`, `plus`, `pro` |
| Roles | `user`, `support`, `admin` |

## 6. Change management for documentation

- Docs live in git beside the code; they are reviewed like code.
- Every PR template includes a "Docs updated?" checkbox (`45_GIT_WORKFLOW.md`).
- Architecture Decision Records: `docs/adr/0001-<slug>.md` using the template in `54_CODING_STANDARDS.md` §9. ADRs are immutable once merged; supersede with a new ADR.
- When an implementation phase finishes, update `53_IMPLEMENTATION_PHASES.md` status table.

## 7. Behavior when information is missing

1. Search the docs (all of them) for the answer.
2. Inspect existing code for an established pattern.
3. If still unresolved and the decision is **reversible and local**, make the smallest decision consistent with the architecture, document it (code comment + doc update), and proceed.
4. If the decision is **irreversible, security-relevant, cost-relevant, or user-visible at product level** (e.g., pricing, data retention, new provider), stop and ask the human owner.

## 8. Document index

| # | Document | Subject |
|---|---|---|
| 00 | MASTER_INSTRUCTION | Rules, priority, glossary |
| 01 | PROJECT_VISION | Vision, users, principles, non-goals |
| 02 | PRD | Personas, journeys, features, MVP, acceptance |
| 03 | REQUIREMENTS | FR/NFR/SEC/etc. with IDs |
| 04 | TECH_STACK | Every technology, why, and where |
| 05 | SYSTEM_ARCHITECTURE | Components and data flows |
| 06 | FOLDER_STRUCTURE | Exact repository layout |
| 07 | DATABASE_ARCHITECTURE | PostgreSQL design rules |
| 08 | DATABASE_SCHEMA | Every table and column |
| 09 | AUTHENTICATION | Sessions, passwords, CSRF, authz middleware |
| 10 | USER_SYSTEM | Profile, preferences, deletion, export |
| 11 | CHAT_SYSTEM | Conversation lifecycle |
| 12 | MESSAGE_SYSTEM | Message tree, parts, edit, regenerate |
| 13 | STREAMING | SSE protocol |
| 14 | GROQ_INTEGRATION | GroqService |
| 15 | MODEL_CONFIGURATION | Model registry |
| 16 | CONTEXT_MANAGEMENT | Prompt assembly and budgets |
| 17 | MEMORY_SYSTEM | Long-term memory |
| 18 | FILE_UPLOADS | Upload pipeline |
| 19 | DOCUMENT_PROCESSING | Extraction/chunking/embedding |
| 20 | RAG_SYSTEM | Retrieval-augmented generation |
| 21 | VECTOR_SEARCH | pgvector |
| 22 | TOOL_SYSTEM | Tool framework |
| 23 | WEB_SEARCH | Web search tool |
| 24 | CODE_EXECUTION | Sandbox |
| 25 | MULTIMODAL | Images, documents, audio, video |
| 26 | VOICE_SYSTEM | STT/TTS |
| 27 | UI_UX_SPECIFICATION | Screens and design system |
| 28 | RESPONSIVE_DESIGN | Breakpoints |
| 29 | COMPONENT_ARCHITECTURE | React structure |
| 30 | API_SPECIFICATION | API conventions |
| 31 | API_ENDPOINTS | Every endpoint |
| 32 | ERROR_HANDLING | Error codes |
| 33 | SECURITY | Threat model and controls |
| 34 | RATE_LIMITING | Redis limits |
| 35 | USAGE_TRACKING | Usage, quotas, cost |
| 36 | ADMIN_PANEL | Admin dashboard |
| 37 | ANALYTICS | Product analytics |
| 38 | LOGGING | Structured logs |
| 39 | MONITORING | Metrics, traces, alerts |
| 40 | TESTING | Test strategy |
| 41 | AI_EVALUATION | Quality evaluation |
| 42 | ENVIRONMENT_VARIABLES | Every env var |
| 43 | DOCKER | Containers and compose |
| 44 | LOCAL_DEVELOPMENT | Developer setup |
| 45 | GIT_WORKFLOW | Branching and commits |
| 46 | CI_CD | GitHub Actions |
| 47 | DEPLOYMENT | Production deploy |
| 48 | PRODUCTION_ARCHITECTURE | Topology and failures |
| 49 | SCALABILITY | Growth stages |
| 50 | BACKUP_AND_RECOVERY | Backups, RPO/RTO |
| 51 | COST_OPTIMIZATION | Cost controls |
| 52 | ROADMAP | Long-term phases |
| 53 | IMPLEMENTATION_PHASES | Executable build plan |
| 54 | CODING_STANDARDS | Conventions |
| 55 | AI_CODING_RULES | Agent rules |
| 56 | DEFINITION_OF_DONE | Completion criteria |
