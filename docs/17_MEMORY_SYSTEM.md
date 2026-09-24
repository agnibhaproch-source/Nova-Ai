# 17 — Memory System

## 1. Types of memory

| Type | Scope | Storage | Lifetime |
|---|---|---|---|
| Short-term (conversational) | One conversation branch | `messages` + `conversations.summary` | Life of conversation |
| Working (turn) | One generation | In-process (`BuiltContext`, tool results) | One turn |
| Long-term | User across conversations | `memories` table (+ embedding) | Until user deletes / retention rule |

Short-term memory is fully specified in `16_CONTEXT_MANAGEMENT.md`. This document covers long-term memory.

## 2. Goals and constraints

- Remember **stable, useful, user-endorsed** facts: preferences, recurring projects, standing instructions, non-sensitive biographical context the user volunteered.
- **Do not** blindly save conversations. Most turns produce **zero** memories.
- Everything is visible and controllable by the user.
- Memory is **off** in effect when `user_preferences.memory_enabled = false`: no extraction, no retrieval.

## 3. Memory record

See `08_DATABASE_SCHEMA.md` §12. Content rules: single self-contained statement, third person about the user ("Prefers TypeScript examples over JavaScript"), ≤ 500 chars, no quotes of third parties' private data.

Categories: `preference`, `biographical`, `project`, `instruction`, `other`. Importance 1–5 (5 = always relevant, e.g., standing instruction).

## 4. Extraction pipeline

Trigger: after an assistant message completes (`status='completed'`), if `memory_enabled` and plan allows memory (`plans.limits.memory = true`; all plans true by default), enqueue `extract_memories(message_id)` **only when a cheap pre-filter passes**:

Pre-filter (in API process, no LLM):
- The user message is ≥ 20 characters, and
- matches at least one heuristic: explicit memory intent (`remember`, `don't forget`, `from now on`, `always`, `never`, `I prefer`, `I'm a`, `I work`, `my name is`, `call me`, `I'm working on`, `I live`) — case-insensitive, English + Hindi transliteration list in `app/services/memory_triggers.py` — **or** the conversation has ≥ 6 user messages and no extraction ran in the last 10 user messages (periodic sweep).

Job `extract_memories`:
1. Lock `nova:{env}:memlock:{user_id}` (SET NX 60 s).
2. Load: the latest user message, the assistant reply (≤ 1,500 chars), up to 4 prior messages for context, and the user's existing active memories (content only, max 100 most important/recent).
3. Call `GroqService.complete_json(purpose="memory_extraction", temperature=0)` with prompt `prompts/memory_extraction.md`:

```
You maintain long-term memory for an assistant. From the USER's messages only, propose memory operations.
Save only information that is (a) about the user, (b) likely useful in future conversations, (c) stable for weeks or longer,
and (d) either explicitly requested to be remembered or clearly volunteered as a preference/standing instruction/ongoing project.
Never save: secrets, passwords, API keys, financial account numbers, government IDs, precise addresses, health conditions,
sexual orientation, religion, political views, criminal history, or information about other people — UNLESS the user explicitly
asked you to remember it, and even then never save secrets/credentials/ID numbers.
Do not save one-off task details, questions, or facts about the world.
Existing memories are listed; prefer "update" over creating near-duplicates; use "delete" if the user asked to forget something.
Return JSON: {"operations":[{"op":"create"|"update"|"delete","memory_id":str|null,"content":str|null,
"category":"preference"|"biographical"|"project"|"instruction"|"other","importance":1-5,"explicit":bool}]}
Return {"operations":[]} if nothing qualifies (this is the most common answer).
```

4. Validate each op (Pydantic). Server-side safeguards:
   - `SensitiveContentFilter`: regexes for credentials/keys (`nova_sk_`, `sk-`, `AKIA`, JWT-like, PEM headers), card numbers (Luhn), Aadhaar/PAN patterns, IFSC+account combos, emails/phones of others → drop op, metric `nova_memory_rejected_total{reason}`.
   - Sensitive categories (health/religion/politics/sexuality) detected by keyword lists → allowed only if `explicit=true` **and** the user message contains explicit memory intent; else drop.
   - `update`/`delete` must reference the user's own memory ids.
   - Max 3 operations per job; max 200 active memories per user (at limit: lowest `importance`, then least recently used `extracted` memory is soft-deleted to make room; user-created memories are never auto-evicted — if all are user-created, the create is dropped and the user is notified in the UI list header).
5. Dedupe: normalize content (lowercase, collapse whitespace, strip punctuation) → `content_hash`; then embedding similarity against existing memories; cosine ≥ 0.92 → convert `create` into `update` of the most similar memory.
6. Embed content via `EmbeddingService`; write rows (`source='extracted'`, `source_conversation_id`, `source_message_id`).
7. If ≥ 1 create/update: publish a user notification in Redis `nova:{env}:notify:{user_id}` (list, TTL 10 min) which the client fetches with the next `GET /api/v1/memories/notifications` poll triggered after `message_complete` (poll once, 3 s after completion) → toast "Memory updated · Manage".
8. Record usage `kind='memory_extraction'`.

## 5. Privacy safeguards (summary)

- Opt-out switch disables extraction & retrieval immediately.
- Sensitive-data filter (step 4) on every write path (including user-created memories: credentials are rejected with `422 MEMORY_CONTENT_REJECTED`).
- Memories are never sent to analytics or logs (log only ids and counts).
- Memory content is sent to Groq only as part of context for that user's own requests and to the self-hosted embedding service.
- Deleting a memory removes it from retrieval immediately (cache invalidation) and hard-deletes after 7 days.
- Data export includes memories; account deletion removes them.

## 6. Importance and retention

- Initial importance from extraction (explicit requests → ≥ 4; instructions → 4–5; incidental preferences → 2–3).
- Decay: nightly job `decay_memories` lowers importance by 1 (not below 1) for `extracted` memories with `last_used_at` older than 90 days (or never used and created > 90 days ago). Extracted memories at importance 1 unused for 180 days are soft-deleted. User-created memories never decay.
- `category='project'` memories older than 180 days without use are soft-deleted.

## 7. Retrieval for context

`MemoryService.select_for_context(user_id, query_text, budget_tokens)`:

1. If memory disabled → `[]`.
2. Always-include set: `category='instruction' AND importance ≥ 4` (max 5, newest first).
3. Semantic set: embed `query_text` (cached) →
   ```sql
   SELECT id, content, category, importance, 1 - (embedding <=> :q) AS sim
   FROM memories
   WHERE user_id = :uid AND deleted_at IS NULL AND embedding_model = :model
   ORDER BY embedding <=> :q
   LIMIT 30;
   ```
   keep `sim ≥ 0.35`.
4. Score = `0.6*sim + 0.4*(importance/5)`; merge with always-include; dedupe; sort by score; take within `budget_tokens` and max 15.
5. Fire-and-forget update `use_count += 1, last_used_at = now()` for selected ids.
6. Return ids (stored in `messages.metadata.memory_ids`).

## 8. User controls (API + UI)

| Action | Endpoint | UI |
|---|---|---|
| List/search | `GET /api/v1/memories?q=&category=&limit=&cursor=` | Settings → Personalization → "Manage memories" dialog with search |
| Create | `POST /api/v1/memories {content, category?, importance?}` → `source='user_created'` | "Add memory" |
| Edit | `PATCH /api/v1/memories/{id} {content?, category?, importance?}` → re-embed | Inline edit |
| Delete | `DELETE /api/v1/memories/{id}` (soft) → `204`; toast with Undo (`POST /api/v1/memories/{id}/restore` within 7 days) | Trash icon |
| Delete all | `DELETE /api/v1/memories?confirm=true` | Danger button with confirmation dialog |
| Toggle | `PATCH /api/v1/users/me/preferences {memory_enabled}` | Switch |
| Notifications | `GET /api/v1/memories/notifications` (pops list) | Toast |

Each message whose context used memories shows a subtle "Used memory" indicator in its action bar with a popover listing the memory contents used (from `metadata.memory_ids`, fetched on click).

## 9. Testing

- Extraction prompt eval set (`evals/datasets/memory_extraction.jsonl`): ≥ 150 cases covering should-save, should-not-save, sensitive, explicit-forget, dedupe → precision ≥ 0.9 for "should-not-save" (false saves are worse than misses).
- Unit tests for `SensitiveContentFilter` patterns.
- Authz tests: user A cannot read/update/delete user B's memories; extraction ops referencing foreign ids are rejected.
- Disable toggle test: no job enqueued, no memories in context.
