# 29 — Frontend Component Architecture

## 1. Layers

```
app/ (routes: layout.tsx, page.tsx)          ← composition only; server components by default
  └─ features/<feature>/components/*          ← feature (container) components: connect data + state + UI
        ├─ features/<feature>/api/*           ← TanStack Query hooks, mutations (data fetching)
        ├─ features/<feature>/hooks/*         ← feature logic hooks (business logic on the client)
        ├─ stores/*                           ← Zustand global client state
        └─ components/ui|common|layout/*      ← presentational components (props in, JSX out)
lib/                                          ← framework-agnostic utilities (api client, sse, formatting)
```

| Layer | May import | Must not |
|---|---|---|
| `components/ui` (shadcn) | `lib/utils` | Fetch data, use stores, know domain types |
| `components/common`, `components/layout` | `ui`, `lib` | Fetch data (layout may read `ui-store` for sidebar state only) |
| `features/*/components` | own feature's api/hooks, stores, `components/*`, other features' **public** `index.ts` exports | Call `fetch` directly; import another feature's internals |
| `features/*/api` | `lib/api/client` | Render JSX |
| `features/*/hooks` | api hooks, stores, lib | Render JSX |
| `app/*` | features' public exports, layout | Contain business logic |

ESLint `import/no-restricted-paths` (or `eslint-plugin-boundaries`) enforces these rules.

## 2. Size and composition rules

- Components ≤ 250 lines (MNT-005); split by responsibility (header / body / actions).
- One exported component per file; file name kebab-case, component PascalCase (`message-item.tsx` → `MessageItem`).
- Props typed with explicit interfaces; no `any`; avoid boolean prop explosions (prefer `variant` unions).
- Server Components for static/SSR pages (landing, pricing, auth layouts); Client Components (`"use client"`) for interactive features. Keep `"use client"` boundaries as low as practical.
- Memoization: `React.memo` for `MessageItem` and `ConversationListItem` (large lists); stable callbacks via `useCallback` only where profiled.

## 3. Chat feature tree

```
app/(app)/c/[conversationId]/page.tsx          (server: validates param, renders <ChatView id=…/>)
└─ features/chat/components/chat-view.tsx       ("use client"; orchestrates)
   ├─ chat-header.tsx                           (title, ModelSelector, FilesPopover, ConversationMenu)
   ├─ message-list.tsx                          (virtualized when > 100 messages; scroll management)
   │   ├─ message-item.tsx                      (switch on role)
   │   │   ├─ user-message.tsx                  (bubble, attachments, edit mode)
   │   │   │   └─ user-message-editor.tsx
   │   │   ├─ assistant-message.tsx             (parts renderer)
   │   │   │   ├─ message-parts.tsx             (maps parts → components)
   │   │   │   │   ├─ markdown/markdown.tsx     (features/markdown)
   │   │   │   │   │   ├─ code-block.tsx
   │   │   │   │   │   ├─ citation-marker.tsx
   │   │   │   │   │   └─ math.tsx
   │   │   │   │   ├─ tool-activity.tsx        (tool_call/tool_result)
   │   │   │   │   │   ├─ web-search-result-view.tsx
   │   │   │   │   │   ├─ calculator-result-view.tsx
   │   │   │   │   │   ├─ file-search-result-view.tsx
   │   │   │   │   └─ code-run-block.tsx        (code part)
   │   │   │   ├─ sources-footer.tsx
   │   │   │   ├─ message-status.tsx            (pending dots, stopped, failed alert, length notice)
   │   │   │   └─ assistant-actions.tsx         (copy, regenerate, feedback, read aloud, more)
   │   │   └─ branch-navigator.tsx
   │   └─ jump-to-latest-button.tsx
   ├─ composer/composer.tsx
   │   ├─ attachment-tray.tsx → attachment-chip.tsx
   │   ├─ composer-textarea.tsx
   │   ├─ composer-toolbar.tsx (attach menu, tool toggles, model chip on mobile)
   │   ├─ dictation-button.tsx (features/voice)
   │   └─ send-stop-button.tsx
   ├─ empty-chat.tsx (greeting + suggestions)
   └─ source-panel.tsx
```

## 4. Data fetching (TanStack Query)

Query keys (single source: `src/lib/query-keys.ts`):

| Key | Endpoint | staleTime |
|---|---|---|
| `['session']` | `/auth/session` | 5 min |
| `['conversations', {archived, deleted}]` (infinite) | `/conversations` | 30 s |
| `['conversation', id]` | `/conversations/{id}` | 30 s |
| `['messages', conversationId]` (infinite, backward) | `/conversations/{id}/messages` | Infinity (mutated by stream events) |
| `['files', filters]`, `['file', id]` | `/files` | 10 s (polling while processing) |
| `['models']` | `/models` | 10 min |
| `['capabilities']` | `/capabilities` | 5 min |
| `['preferences']` | `/users/me/preferences` | 5 min |
| `['memories', q]` | `/memories` | 30 s |
| `['usage','quota']`, `['usage','summary',period]` | `/usage/*` | 30 s |
| `['billing','plans']`, `['billing','subscription']` | `/billing/*` | 5 min / 30 s |
| `['api-keys']`, `['sessions']` | … | 30 s |
| `['admin', …]` | `/admin/*` | 15 s |

Rules:
- Hooks live in `features/<f>/api/use-*.ts`, wrap the typed `apiClient` (openapi-fetch), and throw `ApiError` on non-2xx.
- Mutations use optimistic updates for rename/pin/archive/feedback/preferences with rollback in `onError`.
- Global `QueryClient` defaults: `retry: (count, err) => count < 2 && err.retryable`, `refetchOnWindowFocus: true` except messages.
- `401` from any query → session invalidation → redirect to `/login?next=` (handled in a global `QueryCache.onError`).

## 5. Client state (Zustand)

| Store | State | Persistence |
|---|---|---|
| `ui-store` | `sidebarOpen`, `sidebarCollapsed`, `commandPaletteOpen`, `sourcePanel: {messageId, citationIndex} | null`, `wideMode` | localStorage (sidebar/wide only), try/catch guarded |
| `composer-store` | `drafts: Record<conversationId|'new', {text, fileIds, tools}>` | localStorage (text only, 7 days) |
| `stream-store` | active generations (`13_STREAMING.md` §10) | none |

Stores expose actions; components select minimal slices (`useStreamStore(s => s.streams[id]?.status)`) to avoid re-renders. No server data duplicated in stores except live stream state.

## 6. Business logic hooks

| Hook | Responsibility |
|---|---|
| `useSendMessage(conversationId)` | Create conversation if needed, optimistic user message, open SSE via `streamClient`, route to `/c/{id}`, handle errors (map codes to UI state) |
| `useRegenerate`, `useEditMessage`, `useStopGeneration` | Same pattern for their endpoints |
| `useResumeStream(conversationId)` | Attach to `active_generation_message_id` on load |
| `useFileUpload()` | initiate → XHR upload with progress → complete → poll |
| `useAutoScroll(ref)` | Stick-to-bottom logic |
| `useShortcuts()` | Registers global shortcuts |
| `useQuotaWarnings()` | Derives composer warnings from `['usage','quota']` |
| `useRazorpayCheckout()` | Load script, open checkout, verify |
| `useDictation()` | MediaRecorder lifecycle + transcription call |

## 7. SSE client (`lib/sse`)

- `parseSSE(stream: ReadableStream<Uint8Array>): AsyncGenerator<{id?, event, data}>` — handles chunk boundaries, `\r\n`, comments, multi-line data.
- `streamClient.post(url, body, {idempotencyKey, signal, onEvent})` and `streamClient.resume(messageId, lastEventId, …)` implementing reconnect policy (`13_STREAMING.md` §7).
- Pure TypeScript, unit-tested with fixtures (split chunks at every byte offset).

## 8. Error handling in UI

- `ApiError { status, code, message, requestId, retryable, retryAfter, details }` from the error envelope.
- `errorMessages: Record<ErrorCode, (err) => string>` in `lib/api/errors.ts` — the only place user-facing error copy lives.
- Route segments have `error.tsx` boundaries rendering `ErrorState` with retry; the chat view catches rendering errors per message (`MessageErrorBoundary`) so one malformed message can't break the conversation.
- Sentry captures boundary errors with `request_id` tag; no message content attached.

## 9. Forms

`react-hook-form` + `zod` schemas in `features/<f>/schemas.ts` mirroring server constraints (lengths, formats). Server `VALIDATION_ERROR.details[].field` mapped onto form fields via `setError`.

## 10. Accessibility patterns

- Radix primitives for dialogs, menus, popovers, tooltips, switches, tabs.
- Message list: `role="log"` `aria-live="off"` (announcements via separate live region per `13_STREAMING.md` §10).
- Branch navigator buttons labeled "Previous version" / "Next version", with "2 of 3" text.
- Citation markers are `<button aria-label="Source 2: Q3-report.pdf page 4">`.

## 11. Testing per layer

- `lib/*`: Vitest unit tests (SSE parser, formatters, error mapping).
- Presentational components: RTL render + interaction tests; Storybook is not used (v1).
- Feature components: RTL with MSW handlers (test-only) simulating API and SSE streams.
- E2E: Playwright against the full stack (`40_TESTING.md`).
