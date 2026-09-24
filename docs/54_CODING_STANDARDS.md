# 54 — Coding Standards

## 1. General

- Readability over cleverness; small functions (≤ 60 lines), small modules (Python ≤ 500 lines, components ≤ 250 lines).
- Names are descriptive and domain-aligned with `00_MASTER_INSTRUCTION.md` §5 glossary.
- No dead code, commented-out code, or TODOs without an issue link (`# TODO(#123): …`).
- Comments explain *why*, not *what*. Public functions/classes have docstrings (Python) / TSDoc (TS) when behavior is non-obvious.
- No magic numbers: constants in module-level `UPPER_SNAKE` or settings.
- Every external call has a timeout.
- UTC everywhere in backend; convert to user timezone only in UI.

## 2. Frontend (TypeScript/React)

### 2.1 TypeScript
- `tsconfig`: `"strict": true`, `"noUncheckedIndexedAccess": true`, `"noImplicitOverride": true`, `"exactOptionalPropertyTypes": true`, `"noFallthroughCasesInSwitch": true`.
- No `any` (ESLint `@typescript-eslint/no-explicit-any: error`); use `unknown` + narrowing. No non-null assertions except in tests.
- API types come only from `lib/api/schema.d.ts` (generated). Domain helper types derive from them (`type Message = components["schemas"]["MessageOut"]`).
- Discriminated unions for message parts and SSE events; exhaustive `switch` with `assertNever`.

### 2.2 Components
- Function components only; named exports; one component per file; file kebab-case.
- Props interface `XxxProps` declared above component; children typed explicitly.
- Presentational components are pure (no data fetching, no stores except `ui-store` for layout).
- Styling with Tailwind classes; conditional classes via `cn()`; variants via `class-variance-authority` (shadcn convention).
- Accessibility: semantic elements first; Radix for complex widgets; every icon button has `aria-label`.
- No `useEffect` for derived state; derive during render. Effects only for synchronization with external systems.
- Lists use stable keys (ids), never indexes for dynamic lists.

### 2.3 Naming
| Thing | Convention | Example |
|---|---|---|
| Components | PascalCase | `MessageItem` |
| Hooks | `useX` camelCase | `useSendMessage` |
| Stores | `useXStore` | `useStreamStore` |
| Files | kebab-case | `message-item.tsx`, `use-send-message.ts` |
| Constants | UPPER_SNAKE | `MAX_ATTACHMENTS` |
| Types/interfaces | PascalCase | `StreamState` |
| Query keys | `queryKeys.messages(id)` factory | — |

### 2.4 Hooks & state
- Server state: TanStack Query only. Client state: Zustand slices; select minimal state.
- Custom hooks encapsulate side effects and return typed objects (`{ send, isSending, error }`).
- No global mutable singletons except the query client and stores.

### 2.5 Error handling
- API errors surface as `ApiError`; UI copy only from `lib/api/errors.ts`.
- Error boundaries per route segment and per message.
- Never swallow errors: either handle (UI state) or rethrow/report to Sentry.

### 2.6 Formatting/linting
Prettier (printWidth 100, singleQuote false, trailingComma all); ESLint flat config with `next/core-web-vitals`, `@typescript-eslint/strict-type-checked`, `eslint-plugin-boundaries`, `react/no-danger`, `jsx-a11y`.

## 3. Backend (Python)

### 3.1 Typing & style
- Python 3.12; `from __future__ import annotations` not needed; full type hints; `mypy --strict` on `app/`.
- Ruff rules: `E,F,W,I,N,UP,B,A,C4,SIM,RET,ARG,PTH,ASYNC,S (bandit),T20 (no print),TID (banned imports: groq outside app/ai/groq; test fakes outside tests),PL (selected),RUF`; line length 100; `ruff format`.
- `StrEnum` for enums; `dataclass(frozen=True, slots=True)` for internal value objects; Pydantic models for I/O boundaries.
- Async all the way: no blocking I/O in async functions (CPU-bound → process pool; blocking libs → `anyio.to_thread`).

### 3.2 Service architecture
```
api/v1/<router>.py      → parse/validate (Pydantic), dependencies, call ONE service method, map to response schema
services/<x>_service.py → business rules, authorization, transactions (UnitOfWork), orchestration
repositories/<x>.py     → SQLAlchemy queries; user-scoped methods require user_id
ai/, embeddings/, search/, sandbox/, files/storage.py, billing/ → external adapters behind protocols
workers/tasks/*.py      → thin: load ids, call services
```
- Services receive dependencies via constructor (explicit DI); FastAPI `Depends` providers in `api/deps.py` build them per request (`get_chat_service`).
- No module-level mutable state except clients created in lifespan and stored on `app.state`.

### 3.3 Repositories
- Return ORM models or typed rows; never Pydantic response models.
- Method names: `get_for_user`, `list_for_user`, `insert`, `update_fields`, `soft_delete`, `hard_delete`.
- Use `select()` 2.0 style; eager loading explicit (`selectinload`) to avoid N+1; `text()` only with bound params.

### 3.4 Schemas
- `app/schemas/<area>.py`; suffixes `In` (request), `Out` (response), `Patch` (partial update).
- `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)` for inputs.
- Response models never include secrets/hashes; `from_domain()` classmethods perform mapping.
- Envelope generics: `Envelope[T]`, `ListEnvelope[T]`.

### 3.5 Exceptions
- Raise `AppError` subclasses with `ErrorCode`; never raise `HTTPException` from services.
- Catch exceptions only where you can handle or translate them; never bare `except:`; `except Exception` only at boundaries (tool engine, job runner, handlers) with logging.
- Adapter modules translate third-party exceptions to domain errors.

### 3.6 Dependency injection
- `Depends` for request-scoped resources (db session, principal, services).
- `app.state` for process-scoped clients (Groq client, Redis pool, S3 session, httpx clients, registries) created in `lifespan`.
- Tests override dependencies via `app.dependency_overrides`.

### 3.7 Async & concurrency
- Background tasks use `TaskRegistry` (tracked, cancellable) — no fire-and-forget `asyncio.create_task` without registration.
- Timeouts via `asyncio.timeout()`.
- Locks via Redis for cross-process coordination; never assume a single instance.

## 4. Database

- Migrations: one logical change per migration; descriptive slug; reviewed manually; expand/contract; `CREATE INDEX CONCURRENTLY` on existing large tables; data backfills via jobs.
- Naming per `07_DATABASE_ARCHITECTURE.md` §5; plural tables; `*_id` FKs; `*_at` timestamps; `is_*` booleans.
- Every FK indexed; every user-scoped query indexed with `user_id` first.
- CHECK constraints for enums; NOT NULL by default; nullable only with meaning.
- No triggers containing business logic (only `set_updated_at`).

## 5. Security coding rules

- Never log or return secrets; use `SecretStr`.
- Validate all inputs at boundaries; server re-validates everything the client validated.
- Authorization in services, not only routers.
- Use `secrets` module for tokens; `hmac.compare_digest` for comparisons.
- No `pickle`, `eval`, `exec`, `subprocess` with user input, `yaml.load` (use `safe_load`).
- Outbound fetches only via `SafeFetcher` for untrusted URLs.

## 6. Testing standards

- Test names describe behavior: `test_regenerate_creates_sibling_and_sets_leaf`.
- Arrange-Act-Assert; one behavior per test; factories over fixtures with hidden data.
- No sleeps; use events/polling with timeouts; freeze time.
- Tests must be deterministic and isolated; no reliance on test order.

## 7. Git & reviews

`45_GIT_WORKFLOW.md`.

## 8. Documentation in code

- Module docstring for every service/adapter summarizing responsibility and linking the relevant doc (`See docs/14_GROQ_INTEGRATION.md`).
- Complex algorithms (context budgeting, RRF/MMR, GCRA) have inline references to their spec sections.

## 9. ADR template (`docs/adr/NNNN-title.md`)

```markdown
# NNNN — Title
- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD
- Deciders: …
## Context
## Decision
## Consequences (positive, negative, risks)
## Alternatives considered
## Docs updated
```
