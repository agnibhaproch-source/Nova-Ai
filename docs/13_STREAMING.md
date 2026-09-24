# 13 — Streaming (SSE Protocol)

## 1. Endpoints that stream

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/conversations/{id}/messages` | New turn |
| `POST /api/v1/messages/{id}/regenerate` | Regenerate assistant message |
| `POST /api/v1/messages/{id}/edit` | Edit user message → new branch |
| `GET  /api/v1/messages/{id}/stream` | Resume/attach to an assistant message's stream |

Content negotiation: the three POST endpoints stream when `Accept` includes `text/event-stream` (the web client always sends it). With `Accept: application/json` they block and return the final result (`05_SYSTEM_ARCHITECTURE.md` §5.1). `GET .../stream` always streams.

## 2. Transport

Response headers:

```
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-transform
Connection: keep-alive
X-Accel-Buffering: no
X-Request-ID: <id>
```

Errors detected **before** the stream starts (auth, validation, quota, rate limit, conflicts) are returned as normal JSON error responses with the proper HTTP status — never as SSE.

Frame format (UTF-8, `\n` line endings, blank line terminates an event):

```
id: 7
event: content_delta
data: {"message_id":"6b1...","part_position":0,"delta":"Hello"}

```

- `id` = per-assistant-message monotonically increasing integer sequence starting at 1.
- `data` is always a single-line JSON object.
- Keep-alive comment every 15 s of inactivity: `: ping\n\n`.
- `retry: 2000` is sent once as the first line of the stream.

## 3. Event catalogue

| Event | When | `data` |
|---|---|---|
| `message_start` | First event of a new generation (or first event after resume, see §7) | `{"conversation_id", "user_message": Message|null, "assistant_message": Message}` — `Message` shape as in `12_MESSAGE_SYSTEM.md` §9 (assistant with `status:"pending"`, no parts) |
| `message_snapshot` | Resume only, when replay from `Last-Event-ID` is impossible | `{"message": Message}` — current persisted state; client replaces local state |
| `content_delta` | Text generated | `{"message_id", "part_position": int, "delta": str}` |
| `tool_start` | Tool call validated and starting | `{"message_id", "tool_call_id", "tool_name", "label": str, "arguments": object, "part_position": int}` (`label` e.g. "Searching the web for …") |
| `tool_result` | Tool finished | `{"message_id", "tool_call_id", "tool_name", "status", "summary", "display": object, "latency_ms", "part_position": int}` |
| `citation` | Citation resolved (at finalization) | `{"message_id", "citation": CitationPart}` |
| `usage` | After final Groq call | `{"message_id", "prompt_tokens", "completion_tokens", "total_tokens", "time_to_first_token_ms", "latency_ms", "quota": {"messages_remaining_today": int|null, "tokens_remaining_month": int|null}}` |
| `conversation_updated` | Title generated while stream still open (optional) | `{"conversation_id", "title"}` |
| `message_complete` | Terminal: completed or cancelled | `{"message_id", "status": "completed"|"cancelled", "finish_reason", "message": Message}` (full final message with parts) |
| `error` | Terminal: generation failed | `{"message_id": str|null, "code": ErrorCode, "message": str, "retryable": bool, "retry_after_seconds": int|null}` |

Exactly one terminal event (`message_complete` or `error`) ends every stream; the server then closes the connection.

Typical sequence:

```
retry: 2000
id:1 message_start
id:2..n content_delta ...
id:n+1 tool_start          (optional, repeated)
id:n+2 tool_result
id:... content_delta ...
id:... citation            (0..k)
id:... usage
id:... message_complete
```

## 4. Server architecture

```
POST handler ──► ChatService (txn) ──► GenerationRunner.start(message_id) ──► asyncio.Task (tracked)
                                              │
                                              ▼
                                  GenerationBroker.publish(event)  ── XADD nova:{env}:gen:{message_id}
                                              ▲
POST handler returns EventSourceResponse(broker.subscribe(message_id, after_seq=0))
                                              │ XREAD BLOCK 15000
```

- `GenerationRunner` tasks are registered in a process-level `TaskRegistry` so graceful shutdown (SIGTERM) waits up to 25 s for active generations, then cancels remaining ones, persisting partial text and marking them `failed` with `GENERATION_INTERRUPTED` (retryable).
- Redis key layout (`nova:{env}:` prefix omitted):
  - `gen:{message_id}` — Redis Stream; each entry fields `seq`, `event`, `data`. `XADD ... MAXLEN ~ 10000`.
  - `gen:{message_id}:state` — `running` | `done` (TTL 15 min after done).
  - `gen:{message_id}:cancel` — `1` when cancellation requested (TTL 10 min).
  - After terminal event: `EXPIRE gen:{message_id} 900`.
- Delta coalescing: the runner buffers Groq text chunks and publishes a `content_delta` when ≥ 30 ms have elapsed since the last publish or the buffer ≥ 256 characters, and always before any non-delta event. This bounds event volume without perceptible latency.
- Hard limits: max generation wall time 300 s; if no chunk from Groq for 30 s → abort with `PROVIDER_TIMEOUT`.

## 5. Connection lifecycle

1. Client POSTs with `Accept: text/event-stream`, `X-CSRF-Token`, `Idempotency-Key: <uuid v4>`.
2. Server validates, commits rows, starts generation, returns 200 stream.
3. Events flow; keep-alives every 15 s.
4. Terminal event → server closes.
5. **Client disconnect does not cancel generation.** The SSE handler detects disconnect (`request.is_disconnected()` / send failure), stops reading the broker, and exits; the generation task continues and persists the result.

## 6. Cancellation

- `POST /api/v1/messages/{id}/cancel` (auth + CSRF, owner only) → sets `gen:{id}:cancel`; returns `202`. If the message is already terminal → `200` with current status (idempotent).
- The runner runs a watcher coroutine polling the cancel key every 200 ms (and also subscribes to nothing else); on cancel it sets an `asyncio.Event`, closes the Groq stream (`await stream.close()` / exit the async context manager so the HTTP response is closed), stops any running tool (tool tasks are cancelled; sandbox executions receive `DELETE /v1/executions/{id}`), persists partial content, sets status `cancelled`, `finish_reason='cancelled'`, records usage with `status='cancelled'` using tokens known so far (estimated with `TokenEstimator` if Groq did not report usage), and publishes `message_complete`.
- Deleting a conversation also sets cancel flags for its active generation.
- The client, on Stop, immediately stops rendering new deltas (local `stopping` state) and waits for `message_complete` (or fetches the message after 3 s if the stream is gone).

## 7. Reconnect and resume

- `GET /api/v1/messages/{id}/stream` with header `Last-Event-ID: <seq>` (or query `?last_event_id=` for clients unable to set headers).
- Server logic:
  1. Load message (owner check).
  2. If `gen:{id}` stream exists: `XRANGE` from start; if the earliest retained `seq` ≤ `last_event_id + 1`, replay entries with `seq > last_event_id`, then continue with `XREAD BLOCK` until terminal.
  3. If the stream is missing or trimmed beyond the requested point: emit `message_snapshot` with the persisted message; then, if the message is terminal, emit `message_complete`/`error` accordingly and close; if non-terminal and `gen:{id}:state` is `running`, continue tailing new entries (seq > latest entry at snapshot time); if non-terminal and no state key (generation lost), wait up to 5 s then emit `error {code: GENERATION_INTERRUPTED, retryable: true}` (the reaper will mark it failed).
- Client behavior (`lib/sse/stream-client.ts`):
  - Track `lastEventId` per message.
  - On network error / premature close without terminal event: retry `GET .../stream` with backoff 0.5 s, 1 s, 2 s, 4 s, 8 s, 8 s (6 attempts), then show "Connection lost — Retry" with manual reconnect.
  - On page load, if `meta.active_generation_message_id` is set, attach via `GET .../stream` with `Last-Event-ID: 0`.
  - `visibilitychange` to visible → if a stream is active but no event received in 20 s, reconnect.

## 8. Partial responses

- Partial text is persisted at checkpoints (`12_MESSAGE_SYSTEM.md` §6) and on cancel/failure.
- Failed messages show the partial content (if any) plus an error banner and a Retry button.
- `finish_reason='length'` shows "Response reached the length limit" and a **Continue** action that sends a new user turn with content "Continue" (visible as a normal user message).

## 9. Duplicate prevention

- **Submission idempotency:** `Idempotency-Key` header (client UUID generated once per user submit, reused on retries of the same POST). Stored in `messages.idempotency_key` on the user message with unique `(conversation_id, idempotency_key)`. A repeated POST with the same key returns the stream of the existing assistant child (attach semantics, `Last-Event-ID` 0) instead of creating new rows. Same key with different content → `409 IDEMPOTENCY_KEY_REUSED`.
- **Concurrent generation guard:** conversation lock `conv_gen:{conversation_id}` (SET NX PX 180000, released on terminal); second submit → `409 GENERATION_IN_PROGRESS`.
- **Event dedupe:** client ignores events whose `id` ≤ `lastEventId` (replays after reconnect).
- **Single writer:** only the owning `GenerationRunner` task writes the assistant message while non-terminal; checkpoints use `WHERE status IN ('pending','streaming')` guards so a late write cannot resurrect a cancelled/failed message.

## 10. Frontend state updates

Stores (`29_COMPONENT_ARCHITECTURE.md` §5):

- `stream-store` (Zustand): `Record<messageId, {status, parts: PartState[], lastEventId, tools: Record<toolCallId, ToolState>, citations, usage, error}>`.
- Handlers:
  - `message_start` → insert optimistic user message confirmation (replace temp id with server id) and assistant placeholder into the TanStack Query cache for `['messages', conversationId]`; create stream entry.
  - `content_delta` → append to `parts[part_position].text` (creating the part if absent). Rendering is throttled with `requestAnimationFrame`; markdown re-parse at most every 50 ms; code highlighting deferred until the fence closes.
  - `tool_start` / `tool_result` → upsert tool state; render `ToolActivity` rows.
  - `citation` → add to list; citation markers `[n]` become interactive.
  - `usage` → update quota meter cache (`['usage','quota']`).
  - `conversation_updated` → patch conversation in `['conversations']` cache.
  - `message_complete` → write final `message` into query cache, delete stream entry, invalidate `['conversations']` (ordering) after 1.5 s.
  - `error` → mark message failed in cache with error; toast for non-retryable errors.
- Auto-scroll: stick to bottom while the user is within 80 px of the bottom; if the user scrolls up, show a "Jump to latest" button.
- Screen readers: the message container has `aria-busy="true"` during streaming; completion announced via a visually hidden live region ("Response complete").

## 11. Next.js proxy requirements for SSE

`apps/web/src/app/api/v1/[...path]/route.ts`:

```ts
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;            // Vercel function limit for streaming

async function proxy(req: NextRequest, { params }) {
  const url = `${env.API_INTERNAL_URL}/api/v1/${(await params).path.join("/")}${req.nextUrl.search}`;
  const headers = pickForwardHeaders(req.headers);     // cookie, authorization, content-type, accept,
                                                       // idempotency-key, last-event-id, x-csrf-token, origin, x-request-id
  headers.set("x-nova-proxy-secret", env.API_PROXY_SHARED_SECRET);
  headers.set("x-forwarded-for", clientIp(req));
  const upstream = await fetch(url, {
    method: req.method, headers,
    body: ["GET","HEAD"].includes(req.method) ? undefined : req.body,
    // @ts-expect-error Node fetch streaming request body
    duplex: "half", redirect: "manual", signal: req.signal,
  });
  return new Response(upstream.body, { status: upstream.status, headers: filterResponseHeaders(upstream.headers) });
}
export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
```

- Response headers passed through: `content-type`, `cache-control`, `set-cookie` (all values), `retry-after`, `ratelimit-*`, `x-request-id`, `location`, `content-disposition`.
- No compression of `text/event-stream` responses (Next config `compress: false` for the proxy path is achieved because Route Handler responses are not compressed by Next when streaming; production CDN rules must exclude `text/event-stream` from buffering/compression).
- If the platform cuts the proxy after `maxDuration`, the client resumes via §7; generation continues server-side.

## 12. Degraded mode (Redis unavailable)

If `GenerationBroker` cannot reach Redis at generation start, the runner publishes to an in-process `asyncio.Queue` consumed directly by the originating SSE handler. Resume and cross-instance cancel are unavailable (`/cancel` falls back to an in-process lookup and works only on the same instance; otherwise returns `503 SERVICE_DEGRADED`). Metric `nova_stream_degraded_total` increments and alerts.
