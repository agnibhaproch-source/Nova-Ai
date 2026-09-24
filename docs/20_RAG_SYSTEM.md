# 20 — RAG System

## 1. Purpose

Ground answers in the user's own documents with accurate, verifiable citations, while strictly enforcing that a user can only ever retrieve their own content.

## 2. Components

| Component | Module | Responsibility |
|---|---|---|
| `RagService` | `app/services/rag_service.py` | Orchestrates retrieval for a turn or a tool call |
| `QueryProcessor` | same package | Builds the retrieval query from the conversation |
| `EmbeddingService` | `app/embeddings/service.py` | Query embedding (cached) |
| `ChunkRepository` | `app/repositories/chunk_repository.py` | Vector + full-text queries with mandatory `user_id` filter |
| `Fusion` / `Reranker` | `app/services/rag_ranking.py` | RRF, MMR, thresholding |
| `CitationResolver` | `app/streaming/stream_processor.py` | Maps `[n]` markers in output to sources |

## 3. When retrieval runs

1. **Automatic (per turn):** if the conversation has ≥ 1 attached file with `status='ready'`, or the current message references file ids, `ContextService` calls `RagService.retrieve_for_turn()`.
2. **Tool-driven:** the `file_search` tool (`22_TOOL_SYSTEM.md`) lets the model search the user's **entire library** (or specific files) when the conversation has no attachments or the model needs more.
3. `POST /api/v1/rag/search` — direct search endpoint for the UI "Search my files" feature and debugging (returns chunks, no generation).

## 4. Query processing

`QueryProcessor.build(path, current_message) -> RetrievalQuery`:
1. Base query = current user message text (≤ 2,000 chars).
2. **Follow-up rewriting**: if the message is short (< 12 words) or contains anaphora (`it`, `this`, `that`, `they`, `above`, `same`, `those`) and there is prior conversation, call `GroqService.complete_json(purpose="query_rewrite", temperature=0, max_output_tokens=120)` with the last 4 messages to produce `{"query": "<standalone search query>"}`. Timeout 2 s; on failure/timeout fall back to the concatenation of the previous user message + current message.
3. Keyword query for FTS: `websearch_to_tsquery('simple', query)`.
4. Scope: `file_ids` = explicit ids from message parts ∪ ready files attached to conversation (for turn retrieval); or tool-provided ids / whole library (for tool retrieval).

## 5. Retrieval algorithm (hybrid)

```
q_vec = embed_query(query)                                   # cached 24h
A = vector_search(user_id, scope, q_vec, k=40)               # cosine
B = fulltext_search(user_id, scope, tsquery, k=40)           # ts_rank_cd
R = reciprocal_rank_fusion([A, B], k=60)                     # score = Σ 1/(60 + rank)
R = filter(R, vector_similarity ≥ SIM_THRESHOLD or appears in B top 10)
R = mmr(R, λ=0.7, n=12)                                      # diversity by embedding cosine
R = neighbor_expand(R)                                       # optionally merge adjacent chunks (same file, index±1) when both selected
R = fit_to_budget(R, token_budget, max_chunks=8)
assign citation_index 1..n (ordered by fused score)
```

Parameters (config `app/core/config.py` → `RagSettings`): `RAG_TOP_K_VECTOR=40`, `RAG_TOP_K_FTS=40`, `RAG_FINAL_MAX_CHUNKS=8`, `RAG_SIM_THRESHOLD=0.25` (tunable per embedding model; see `21_VECTOR_SEARCH.md` §6), `RAG_MMR_LAMBDA=0.7`.

If `R` is empty after thresholding: no `<retrieved_documents>` block is added; instead a system note: "The user's attached documents contain no passages relevant to this question." — the model is instructed to say so rather than guess.

### 5.1 Reranking
v1 uses RRF + MMR (no cross-encoder). `Reranker` protocol exists with `NoopReranker`; a self-hosted cross-encoder via TEI's `/rerank` endpoint (`TEIReranker`, enabled by `RERANKER_ENDPOINT`) is a Phase 11 option, evaluated with `41_AI_EVALUATION.md` before enabling. Never a hosted LLM vendor.

## 6. Filtering and permission enforcement

Every chunk query **must** include all of:
```sql
WHERE dc.user_id = :user_id
  AND dc.file_id = ANY(:file_ids)                 -- scope (omitted only for whole-library search)
  AND f.id = dc.file_id AND f.user_id = :user_id
  AND f.status = 'ready' AND f.deleted_at IS NULL
  AND dc.embedding_model = :current_embedding_model
```
- `file_ids` supplied by callers are first intersected with the user's owned ready files in SQL; foreign ids are silently dropped (and logged as `rag.scope_foreign_id` WARN, metric).
- `ChunkRepository` methods take `user_id` as a required positional parameter; there is no method without it. A unit test asserts every SQL string in `ChunkRepository` contains `user_id`.
- Security test: user B's chunk nearest to user A's query is never returned (`40_TESTING.md` §6).

## 7. Context selection and formatting

Chunks are rendered into the `<retrieved_documents>` block (`16_CONTEXT_MANAGEMENT.md` §11) with header line `[n] source: "{filename}", page {page} | sheet "{sheet}" | slide {n}, section "{section}"` followed by the chunk text without its contextual header. Chunks from the same file are kept in fused-score order (not document order) to keep `[n]` stable.

The system prompt instructs: cite with `[n]`; do not cite numbers not present; if sources conflict, say so; if the answer isn't in the documents, say that explicitly and optionally answer from general knowledge labeled as such.

## 8. Citations

- During streaming, `StreamProcessor` scans text for markers matching `\[(\d{1,2})\]` (also `[1, 2]` and `[1][2]` variants).
- Valid indices (present in the retrieved set) are collected; invalid indices are left as text and counted in metric `nova_rag_invalid_citation_total` (eval signal).
- At finalization, one `citation` part per used source index (ordered by index) is inserted with source metadata (§9), and `citation` SSE events are emitted.
- Frontend renders markers as superscript pills; hover/tap shows a popover (filename, page, snippet ≤ 300 chars); click opens the **Source panel** (right drawer) with the full chunk text and "Open file" (download) action.
- Sources used but never cited are not shown (the UI can show "Searched N documents" in a collapsed activity row).
- Web citations share the same mechanism with `source_type='web'` (`23_WEB_SEARCH.md`); numbering is unified per message: RAG chunks first (1..n), web results continue (n+1..).

## 9. Source metadata (citation part `data`)

```json
{"index": 2, "source_type": "file", "file_id": "uuid", "chunk_id": "uuid",
 "filename": "Q3-report.pdf", "page_number": 4, "sheet_name": null,
 "section_title": "Risks", "snippet": "Supply-chain disruptions remain…"}
```

If the file is later deleted, the citation remains in the message but the UI shows "Source deleted" and disables "Open".

## 10. `POST /api/v1/rag/search`

Request: `{"query": str (1..1000), "file_ids": [uuid]?, "conversation_id": uuid?, "top_k": int (1..20, default 8)}`
Response: `{"data": [{"chunk_id","file_id","filename","page_number","sheet_name","section_title","content","score"}]}`
Auth: session or API key with `files:read`; rate limit `rag_search` (30/min).

## 11. Observability and quality

- Span `rag.retrieve` attributes: `nova.rag.scope_files`, `nova.rag.candidates_vec`, `nova.rag.candidates_fts`, `nova.rag.selected`, `nova.rag.rewrite_used`, `nova.rag.empty`.
- Store selected chunk ids and scores in `messages.metadata.rag` for evaluation and debugging (ids only).
- Quality measured by `41_AI_EVALUATION.md` (recall@k, citation precision, faithfulness).
