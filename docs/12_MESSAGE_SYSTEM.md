# 12 — Message System

## 1. Data model summary

- `messages`: one row per user or assistant message; tree via `parent_message_id`.
- `message_parts`: ordered typed parts per message.
- `tool_calls`: one row per tool invocation requested by an assistant message.
- `messages.content_text`: denormalized concatenation of `text` parts (and `code` part source for user messages) joined by `\n\n` — used for search and context building. Always recomputed by `MessageService` when parts change; never edited directly.

## 2. Roles

| Role | Stored? | Meaning |
|---|---|---|
| `user` | yes | Human (or API client) input |
| `assistant` | yes | Model output for a turn (includes its tool calls/results as parts) |
| `system` | reserved, not stored in v1 | System prompts are built dynamically per request (`16_CONTEXT_MANAGEMENT.md`) |
| `tool` | reserved, not stored in v1 | Tool results are stored in `tool_calls` + parts, and converted to Groq `tool` role messages at request time |

The CHECK constraint includes all four for forward compatibility.

## 3. Message parts

| type | Used by | Columns | `data` JSON schema |
|---|---|---|---|
| `text` | user, assistant | `text_content` (markdown) | `{}` |
| `image` | user | `file_id` | `{"mime_type": str, "width": int, "height": int, "alt": str|null}` |
| `file` | user | `file_id` | `{"filename": str, "mime_type": str, "size_bytes": int}` |
| `citation` | assistant | — | `{"index": int, "source_type": "file"|"web", "file_id": uuid|null, "chunk_id": uuid|null, "filename": str|null, "page_number": int|null, "sheet_name": str|null, "section_title": str|null, "url": str|null, "title": str|null, "site_name": str|null, "published_at": str|null, "snippet": str (≤300 chars)}` |
| `tool_call` | assistant | `tool_call_id` | `{"tool_name": str, "arguments": object, "iteration": int}` |
| `tool_result` | assistant | `tool_call_id` | `{"tool_name": str, "status": "succeeded"|"failed"|"timed_out"|"denied", "summary": str (≤500 chars), "display": object, "error_code": str|null}` |
| `code` | assistant (code execution) | `tool_call_id`, `text_content` = source code | `{"language": "python", "stdout": str, "stderr": str, "exit_code": int|null, "timed_out": bool, "truncated": bool, "duration_ms": int}` |

Rules:
- Pydantic discriminated union `MessagePart = TextPart | ImagePart | FilePart | CitationPart | ToolCallPart | ToolResultPart | CodePart` in `app/schemas/message_parts.py`; `data` validated before insert.
- Positions are contiguous from 0. Assistant parts are appended in production order: e.g. `text(0)`, `tool_call(1)`, `tool_result(2)`, `text(3)`, `citation(4)`, `citation(5)`. Consecutive text deltas are merged into the current open `text` part; a new `text` part starts after any tool part.
- For `code_execution`, the `tool_result` part is replaced by a `code` part (the UI renders a code-run block).
- Citations are appended at message finalization, deduplicated by source, ordered by `index`.
- Markdown code fences in normal assistant text stay inside `text` parts (rendered by the markdown renderer); the `code` part type is only for executed code.

## 4. Statuses and lifecycle

```
user message:       completed (on insert)

assistant message:  pending ──first delta──► streaming ──finish──► completed
                       │                         │
                       │                         ├── user stop ──► cancelled
                       │                         └── error ──────► failed
                       ├── user stop before first token ─► cancelled
                       └── error before first token ─────► failed
```

| Status | Meaning | `finish_reason` | UI |
|---|---|---|---|
| pending | Row created, generation not yet producing text | NULL | Typing indicator |
| streaming | Deltas being produced | NULL | Live text + cursor |
| completed | Finished normally | `stop` / `length` / `content_filter` | Normal; `length` shows "Response truncated — Continue" hint |
| cancelled | Stopped by user or conversation deletion | `cancelled` | "Stopped" label, partial text kept |
| failed | Provider/internal error | `error` | Error banner + Retry (= regenerate) |

Transitions are enforced in `MessageService.transition(message, to_status)` with an allowed-transition map; illegal transitions raise `InvalidStateError` (500 + alert).

Stale detection: messages in `pending/streaming` whose `updated_at < now() - 120 s` are marked `failed` with `error_code='GENERATION_INTERRUPTED'` by `reap_stale_generations` (every 30 s). The running generation task touches `updated_at` at least every 10 s (heartbeat via checkpoint).

## 5. Ordering

- Within a conversation, the **display order** is the path from root to `current_leaf_message_id`, obtained by walking `parent_message_id` upward:
  ```sql
  WITH RECURSIVE path AS (
    SELECT m.*, 0 AS depth FROM messages m WHERE m.id = :leaf_id AND m.conversation_id = :cid
    UNION ALL
    SELECT p.*, path.depth + 1 FROM messages p JOIN path ON p.id = path.parent_message_id
  )
  SELECT * FROM path ORDER BY depth DESC;
  ```
- Siblings (same parent) ordered by `sibling_index` (assigned at insert as `COALESCE(MAX(sibling_index)+1, 0)` among siblings, computed under the conversation generation lock).
- Parts ordered by `position`.

## 6. Persistence during streaming

`StreamProcessor` (in `GenerationRunner`) persists incrementally:

- On first delta: status → `streaming`, `time_to_first_token_ms` set.
- **Checkpoint** every 1 s or every 2,000 new characters (whichever first): upsert the current open text part's `text_content` and `messages.content_text`, touch `updated_at`. Short transaction each time.
- On tool call start/finish: insert/update `tool_calls` + parts immediately.
- On finish: final checkpoint + citations + status + `finish_reason` + token counts + `latency_ms` + `completed_at` in one transaction; then `usage_records` insert; then after-commit hooks (title job, memory extraction job, summary check, analytics `message_completed`).
- Crash between checkpoints loses ≤ 1 s of text; the reaper marks the message failed; the user can regenerate.

## 7. Regeneration

`POST /api/v1/messages/{message_id}/regenerate` body `{model_key?: str}` → SSE.

1. Load message owned by principal; must be `role='assistant'` with terminal status → else `409 INVALID_MESSAGE_STATE`.
2. Acquire conversation generation lock; quota checks as for a new message.
3. Insert new assistant message: same `parent_message_id` (the user message), `sibling_index = next`, status `pending`, `model_key` = body or conversation model.
4. Set `current_leaf_message_id` = new message.
5. Run generation with context built from the path ending at the parent user message.
6. Previous sibling remains unchanged and navigable.

"Retry" on a failed message is the same operation.

## 8. Editing

`POST /api/v1/messages/{message_id}/edit` body `{content: str, file_ids?: [uuid]}` → SSE.

1. Message must be `role='user'` and owned → else `409 INVALID_MESSAGE_STATE` / 404.
2. Validation as in `11_CHAT_SYSTEM.md` §4. If `file_ids` omitted, the new message inherits the original's file/image parts.
3. Insert new user message as a **sibling** (same `parent_message_id`, next `sibling_index`), then a new pending assistant child; set `current_leaf_message_id` to the assistant.
4. Stream generation.
5. If the conversation summary covers messages beyond the edit point (`summary_through_message_id` not an ancestor of the new leaf), the summary is ignored for this branch and a resummarization is scheduled if needed (`16_CONTEXT_MANAGEMENT.md` §6).

Assistant messages cannot be edited by users (v1).

## 9. Reading messages

`GET /api/v1/conversations/{id}/messages?limit=50&before=<message_id>`

- Returns the **current path** (root→leaf), newest `limit` messages; `before` pages toward the root.
- Response:
```json
{
  "data": [
    {
      "id": "uuid", "role": "user", "status": "completed", "parent_message_id": null,
      "created_at": "...", "completed_at": "...",
      "model_key": null, "finish_reason": null, "error": null,
      "parts": [{"id":"uuid","position":0,"type":"text","text":"Hello"}],
      "siblings": {"index": 0, "count": 2, "prev_id": null, "next_id": "uuid"},
      "feedback": null,
      "usage": null
    }
  ],
  "page": {"has_more": false, "next_cursor": null},
  "meta": {"current_leaf_message_id": "uuid", "active_generation_message_id": "uuid|null"}
}
```
- `active_generation_message_id` lets the client resume a stream on page load (`13_STREAMING.md` §7).
- Part serialization: `text`/`code` → `text` field; others → typed fields from `data`; file/image parts include `file: {id, filename, mime_type, status, thumbnail_url?}` (presigned 1 h for images).
- `GET /api/v1/messages/{id}` returns a single message in the same shape.

Switch branch with `POST /api/v1/conversations/{id}/branch` (`11_CHAT_SYSTEM.md` §13), used by the `< 2/3 >` navigator.

## 10. Copy, report

- Copy is client-side: copies the markdown source of `text` parts (code blocks have their own copy button).
- `POST /api/v1/messages/{id}/report {category, details?}` → creates `moderation_flags(source='user_report')`, returns `201`.

## 11. Feedback

- `PUT /api/v1/messages/{id}/feedback {rating: "up"|"down", reasons?: [..], comment?: str}` → upsert on (user_id, message_id); only for assistant messages in terminal status.
- `DELETE /api/v1/messages/{id}/feedback` → remove.
- Down-votes open a small dialog with reason chips (`inaccurate`, `not_helpful`, `harmful`, `incomplete`, `wrong_citation`, `too_long`, `too_short`, `other`) and optional comment.
- Feedback feeds the evaluation pipeline (`41_AI_EVALUATION.md` §7) as metadata only; message content is accessed only through the admin content-access procedure.

## 12. Limits

| Limit | Value |
|---|---|
| User message text | 32,000 chars (plan may reduce: free 8,000) |
| Attachments per message | 10 files / 4 images |
| Branches per parent | 50 siblings (`409 LIMIT_REACHED`) |
| Messages per conversation | 5,000 (`409 LIMIT_REACHED`, suggest new chat) |
| Stored tool result | 256 KB JSON (truncated with `truncated: true`) |
