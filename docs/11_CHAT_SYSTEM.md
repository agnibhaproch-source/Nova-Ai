# 11 — Chat System (Conversation Lifecycle)

## 1. Concepts

- **Conversation:** owned by one user; contains a **tree** of messages (branches from edits/regenerations). Exactly one branch is "current", identified by `conversations.current_leaf_message_id`.
- **Turn:** one user message + the assistant message generated in response (plus tool calls within it).
- Service boundaries: `ConversationService` (CRUD, listing, search, title), `MessageService` (tree operations, persistence), `ChatService` (turn orchestration), `GenerationRunner` (Groq loop).

## 2. State diagram

```
             create (first message)
                   │
                   ▼
   ┌────────── ACTIVE ◄──────────── unarchive ────────┐
   │  pin/unpin, rename, send, edit, regenerate        │
   │           │ archive                                │
   │           ▼                                        │
   │       ARCHIVED ────────────────────────────────────┘
   │           │ delete
   ▼ delete    ▼
  TRASHED (deleted_at set) ── restore (≤30 days) ──► previous state (archived_at preserved)
   │
   │ purge (30 days) or "delete permanently"
   ▼
  GONE (hard delete, cascade)
```

## 3. Create conversation

Two supported paths; the web app uses **path A**.

**A. Create then send (web):**
1. User types in `/chat` and submits.
2. Client `POST /api/v1/conversations {model_key?}` → `201 {data: conversation}`; `model_key` defaults to `preferences.default_model_key` or registry default, validated against plan.
3. Client immediately `POST /api/v1/conversations/{id}/messages` (SSE) with the message; then `router.replace('/c/{id}')` after `message_start` arrives (URL change without remount: the chat view component is shared between `/chat` and `/c/[id]` via the `ChatView` feature component keyed by a client-generated draft id).
4. Empty conversations (no messages) older than 1 hour are removed by `purge_empty_conversations` (hourly) and are hidden from lists (`message_count = 0` filtered).

**B. API clients:** same two calls.

Rules:
- Max 10,000 non-deleted conversations per user (`409 LIMIT_REACHED` beyond; practically never hit).
- `title='New chat'`, `title_source='default'`.

## 4. First and subsequent messages

`ChatService.submit_user_message(principal, conversation_id, SubmitMessageInput)`:

```python
SubmitMessageInput:
  content: str                     # 1..32_000 chars after trim (plan may lower)
  parent_message_id: UUID | None   # default: conversation.current_leaf_message_id
  file_ids: list[UUID] = []        # ≤ 10; must be owned and status in ('ready','processing') 
  model_key: str | None            # overrides conversation.model_key for this turn and updates it
  tools: ToolToggles | None        # {"web_search": bool, "code_execution": bool} per-turn override (only narrowing prefs)
  idempotency_key: str | None      # from Idempotency-Key header
```

Steps (all before any Groq call):
1. Load conversation owned by principal (404 otherwise); reject if trashed (`409 CONVERSATION_DELETED`). Archived conversations are unarchived automatically on send.
2. Idempotency: if `(conversation_id, idempotency_key)` exists → return existing assistant message stream (resume) instead of creating new rows (`13_STREAMING.md` §9).
3. Validate `parent_message_id` belongs to conversation and is an `assistant` message with terminal status (or NULL for the first message). Sending while another generation in the same conversation is `pending/streaming` → `409 GENERATION_IN_PROGRESS` (lock key `nova:{env}:conv_gen:{conversation_id}` SET NX with TTL 180 s).
4. Rate limits and quotas: `chat_messages` user limit, `QuotaService.check_and_reserve(user, estimated_tokens)` (`35_USAGE_TRACKING.md` §6).
5. Validate model allowed for plan and capable of the input (images require `supports_vision`) → `422 MODEL_CAPABILITY_MISSING`.
6. Transaction:
   - Insert user message (`role='user'`, `status='completed'`, parts: text + file/image parts, `sibling_index = count(siblings)`).
   - Upsert `conversation_files` for each file.
   - Insert assistant message (`role='assistant'`, `status='pending'`, `parent_message_id=user_msg.id`, `model_key`, `groq_model_id`).
   - Update conversation: `current_leaf_message_id=assistant.id`, `last_message_at=now()`, `message_count += 2`, `model_key` if changed.
7. After commit: start `GenerationRunner` task (`13_STREAMING.md` §4) and return the SSE stream.

## 5. Title generation

Trigger: first assistant message in a conversation reaches `completed` and `title_source='default'`.

- Job: `generate_title(conversation_id)` enqueued to ARQ (runs within ~1 s).
- Input: first user message (≤ 2,000 chars) + first assistant response (≤ 1,000 chars).
- Call: `GroqService.complete(model_key='fast' → fallback 'primary', temperature=0.3, max_tokens=24, purpose='title')` with prompt `app/ai/prompts/title.md`:
  > "Write a concise title (max 6 words) for this conversation. No quotes, no trailing punctuation, same language as the user. Respond with the title only."
- Post-process: strip quotes/markdown/newlines, collapse whitespace, truncate to 60 chars at a word boundary; if empty → first 40 chars of user message.
- Update only if still `title_source='default'` (conditional UPDATE `WHERE title_source='default'`) → `title_source='generated'`.
- Notify: publish `conversation_updated` to the message's generation stream if still open, and the client also invalidates the `conversations` query on `message_complete` after 1.5 s. Usage recorded with `kind='title'` (does **not** count toward the user's message quota; tokens do count toward the monthly token quota).

## 6. Rename

`PATCH /api/v1/conversations/{id} {title}` → trim, 1–200 chars, strip control characters → `title_source='user'`. Audit not required (user-level content). Returns updated conversation.

## 7. Pin, archive, unarchive

- `PATCH {pinned: true|false}` → `pinned_at = now() | NULL`. Max 20 pinned (`409 LIMIT_REACHED`).
- `PATCH {archived: true|false}` → `archived_at = now() | NULL`. Archived conversations leave the main list and appear under Settings → Data → Archived chats and via `GET /conversations?archived=true`. Pinned + archived → unpins.

## 8. Delete, restore, purge

- `DELETE /api/v1/conversations/{id}` → soft delete (`deleted_at=now()`); cancels an active generation (sets cancel flag). `204`.
- `GET /api/v1/conversations?deleted=true` → trash list (sorted `deleted_at DESC`), with `purge_at = deleted_at + 30 days`.
- `POST /api/v1/conversations/{id}/restore` → allowed if `deleted_at > now() - 30 days` → `deleted_at=NULL`.
- `DELETE /api/v1/conversations/{id}?permanent=true` → only for trashed conversations → hard delete (cascade). Attached files are **not** deleted (files belong to the user's library).
- Bulk: `POST /api/v1/conversations/bulk-delete` (see `10_USER_SYSTEM.md` §11).

## 9. Search

`GET /api/v1/conversations/search?q=<1..200 chars>&limit=20&cursor=`

Algorithm (`ConversationRepository.search`):
1. Normalize query; build `websearch_to_tsquery('simple', :q)`.
2. Candidate A — message matches:
   ```sql
   SELECT m.conversation_id, m.id AS message_id,
          ts_rank_cd(m.content_tsv, q) AS rank,
          ts_headline('simple', left(m.content_text, 5000), q,
             'StartSel=<<,StopSel=>>,MaxWords=18,MinWords=8,MaxFragments=1') AS snippet
   FROM messages m JOIN conversations c ON c.id = m.conversation_id
   WHERE m.user_id = :uid AND c.deleted_at IS NULL
     AND m.role IN ('user','assistant') AND m.content_tsv @@ q
   ```
3. Candidate B — title matches: `c.title ILIKE '%' || :q || '%' OR similarity(c.title, :q) > 0.3` (trigram).
4. Merge: group by conversation; score = `max(message_rank) + 0.5 if title match`; order by score DESC, `last_message_at` DESC.
5. Return `{conversation_id, title, snippet (<< >> markers converted to `highlights` offsets), message_id, last_message_at}`.
6. UI (`Cmd/Ctrl+K`): debounced 200 ms; selecting opens `/c/{id}?m={message_id}` which scrolls to and briefly highlights the message (switching branch if the message is not on the current branch, via `POST /conversations/{id}/branch`).

Performance: `ix_messages_*` GIN on `content_tsv` + `user_id` filter; p95 ≤ 300 ms for 100k messages per user.

## 10. Listing and pagination

`GET /api/v1/conversations?limit=30&cursor=<opaque>&archived=false&deleted=false`

- Sort: pinned first (`pinned_at DESC`), then `last_message_at DESC, id DESC`.
- Cursor = base64url JSON `{"p": pinned_at|null, "t": last_message_at, "id": id}`; keyset predicate.
- Filters out `message_count = 0`.
- Item shape: `{id, title, model_key, pinned, archived, last_message_at, created_at}`.
- Sidebar groups client-side by user timezone: Pinned, Today, Yesterday, Previous 7 days, Previous 30 days, then `MMMM yyyy`.

## 11. Get conversation

`GET /api/v1/conversations/{id}` → conversation metadata + `current_leaf_message_id` + attached files summary. Messages via `GET /api/v1/conversations/{id}/messages` (`12_MESSAGE_SYSTEM.md` §9).

## 12. Ownership

Every conversation operation calls `ConversationRepository.get_for_user(principal.user_id, id)`. API keys need scope `conversations:read` for GET endpoints, `conversations:write` for PATCH/DELETE, `chat:write` for sending messages. Admins never use user endpoints to access others' conversations; they use `/admin/*` (`36_ADMIN_PANEL.md`).

## 13. Branch switching

`POST /api/v1/conversations/{id}/branch {message_id}` → verifies ownership, then sets `current_leaf_message_id` to the **most recently created leaf** in the subtree rooted at `message_id`:

```sql
WITH RECURSIVE sub AS (
  SELECT id, created_at FROM messages WHERE id = :message_id AND conversation_id = :cid
  UNION ALL
  SELECT m.id, m.created_at FROM messages m JOIN sub ON m.parent_message_id = sub.id
)
SELECT s.id FROM sub s
WHERE NOT EXISTS (SELECT 1 FROM messages c WHERE c.parent_message_id = s.id)
ORDER BY s.created_at DESC LIMIT 1;
```

Returns the new active path (same shape as the messages endpoint).
