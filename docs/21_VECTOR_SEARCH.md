# 21 — Vector Search (pgvector)

## 1. Embedding abstraction (independent of Groq)

Embeddings are **not** produced by Groq and **not** by any prohibited hosted LLM vendor. They come from a self-hosted open-weights embedding model served by Hugging Face Text Embeddings Inference (TEI).

```python
class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int
    async def embed(self, texts: Sequence[str], *, input_type: Literal["document","query"]) -> list[list[float]]: ...

class TEIEmbeddingProvider(EmbeddingProvider):
    # POST {EMBEDDING_ENDPOINT}/embed  body {"inputs": [...], "truncate": true, "normalize": true}
    # Verify request/response shape against the TEI version deployed.
    ...

class EmbeddingService:
    async def embed_documents(self, texts) -> list[list[float]]
    async def embed_query(self, text) -> list[float]      # Redis cache nova:{env}:emb:q:{sha256(model|text)} 24h
```

- `input_type` lets models that need prefixes work: `EMBEDDING_QUERY_PREFIX` and `EMBEDDING_DOCUMENT_PREFIX` env vars (default empty) are prepended by the provider. The operator sets them per the chosen model's documentation.
- Model choice is an operator decision recorded in `EMBEDDING_MODEL`; these docs deliberately do not choose one. Selection criteria: open weights, license permits commercial use, multilingual (English + Indian languages) if possible, dimension ≤ 2000 (pgvector HNSW limit for `vector`), good retrieval benchmarks.
- Test double: `tests/fakes/embeddings.py` (`HashEmbeddingProvider`, deterministic hashing) — test-only, refused outside `APP_ENV=test`.
- HTTP client: `httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))`, optional `Authorization: Bearer {EMBEDDING_API_KEY}` when the TEI deployment is protected.

## 2. Storage

- Columns: `document_chunks.embedding vector(D)`, `memories.embedding vector(D)` where `D = EMBEDDING_DIMENSIONS`.
- `embedding_model varchar(200)` stored per row = `EMBEDDING_MODEL` at write time.
- Vectors normalized to unit length before storage.
- SQLAlchemy: `from pgvector.sqlalchemy import Vector`; `embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.EMBEDDING_DIMENSIONS))`. Register asyncpg codec via `pgvector.asyncpg.register_vector` on connect (`event.listen(engine.sync_engine, "connect", ...)` with `run_async`).

## 3. Dimensions

Fixed per deployment. Migration `0010_chunks_vector` reads `EMBEDDING_DIMENSIONS` from settings and emits `vector({D})`; it aborts if unset or > 2000. A startup check compares the column's declared dimension (`SELECT atttypmod FROM pg_attribute ...`) with settings and refuses to start on mismatch.

## 4. Distance metric

Cosine distance (`<=>`) with `vector_cosine_ops`. Similarity = `1 - distance`. (With normalized vectors, inner product would be equivalent; cosine is chosen for robustness if a model returns unnormalized vectors.)

## 5. Indexes

```sql
CREATE INDEX CONCURRENTLY ix_document_chunks_embedding_hnsw
  ON document_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX CONCURRENTLY ix_memories_embedding_hnsw
  ON memories USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX ix_document_chunks_user_file ON document_chunks (user_id, file_id);
CREATE INDEX ix_document_chunks_tsv ON document_chunks USING gin (content_tsv);
```

Query-time: `SET LOCAL hnsw.ef_search = 100;` inside the retrieval transaction.

### 5.1 Filtered search strategy
HNSW is a global index; filtering by `user_id` after ANN can return too few rows for users with few chunks among many. Strategy by scope size (count of candidate chunks computed cheaply from `files.chunk_count` sum):

| Scope chunk count | Query plan |
|---|---|
| ≤ 20,000 | **Exact search**: disable index use for the query (`SET LOCAL enable_indexscan = off` is too broad; instead use a CTE with `MATERIALIZED` filtered rows then `ORDER BY embedding <=> :q LIMIT k`) — exact, fast for small sets, perfect recall |
| > 20,000 | HNSW with iterative scan: `SET LOCAL hnsw.iterative_scan = relaxed_order` (pgvector ≥ 0.8) and `hnsw.max_scan_tuples = 40000`; if pgvector < 0.8, over-fetch `LIMIT k*10` via index then filter |

Exact search query:
```sql
WITH scoped AS MATERIALIZED (
  SELECT dc.id, dc.file_id, dc.embedding
  FROM document_chunks dc
  JOIN files f ON f.id = dc.file_id
  WHERE dc.user_id = :uid AND f.user_id = :uid AND f.status = 'ready' AND f.deleted_at IS NULL
    AND dc.file_id = ANY(:file_ids) AND dc.embedding_model = :model
)
SELECT id, file_id, 1 - (embedding <=> :q) AS similarity
FROM scoped ORDER BY embedding <=> :q LIMIT :k;
```

Phase 11 option for very large tenants: partial HNSW indexes are not per-user feasible; instead evaluate table partitioning by `hash(user_id)` (16 partitions) with per-partition HNSW indexes (`49_SCALABILITY.md`).

## 6. Similarity threshold and top-K

| Use | top-K candidates | final | threshold |
|---|---|---|---|
| RAG turn retrieval | 40 vec + 40 FTS | ≤ 8 chunks | `RAG_SIM_THRESHOLD` (default 0.25) |
| file_search tool | 40 + 40 | ≤ 10 | same |
| Memory retrieval | 30 | ≤ 15 | 0.35 |
| Memory dedupe | 5 | 1 | 0.92 |

Thresholds are model-dependent. Calibration procedure (required when the embedding model changes): run `evals/nova_evals/calibrate_threshold.py` over the RAG eval set; choose the threshold maximizing F1 of relevant-chunk detection; record it in `.env` and the eval report.

## 7. Filtering rules

Always filter by `user_id` (both on chunk and file), file status/deletion, and current `embedding_model`. Optional filters: `file_ids`, `kind`, `created_after`. Filters are applied **inside** the CTE/WHERE, never post-hoc in Python.

## 8. Migrations

- `0010_chunks_vector`: create `document_chunks` with `vector(D)`, HNSW index (`CONCURRENTLY` not possible inside the creating transaction for a new empty table — use plain `CREATE INDEX` there).
- `0011_memories`: same for `memories`.
- Index maintenance: `REINDEX INDEX CONCURRENTLY` only if bloat > 30% (Phase 11 runbook).

## 9. Changing the embedding model

1. ADR describing the new model and dimension.
2. If the dimension changes: migration adds `embedding_v2 vector(D2)` + HNSW index on it (expand).
3. Deploy with `EMBEDDING_MODEL_NEXT`, `EMBEDDING_DIMENSIONS_NEXT`, `EMBEDDING_ENDPOINT_NEXT`; the `reembed` job fills `embedding_v2` for all chunks and memories in batches (low-priority queue), tracking progress in Redis.
4. When 100% complete: flip settings so queries use the new column/model; recalibrate thresholds.
5. Contract migration drops the old column and index; rename.
If the dimension is unchanged, re-embed into the same column with `embedding_model` distinguishing old/new rows; queries filter by the new model only after completion (until then, the old model is used).
