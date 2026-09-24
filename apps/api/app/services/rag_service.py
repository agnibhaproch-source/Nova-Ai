"""RagService: permission-scoped hybrid retrieval with citations (docs/20, docs/21).

Every query filters by user_id on both chunk and file, file status, and deletion. When no
embedding model is configured (or a chunk has no vector), retrieval degrades to full-text only.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.tokens import estimate
from app.core.config import get_settings
from app.documents.chunker import strip_header
from app.embeddings.service import get_embeddings
from app.models import ConversationFile, File

log = structlog.get_logger("app.rag")

VEC_SQL = text(
    """
    WITH scoped AS MATERIALIZED (
      SELECT dc.id, dc.embedding FROM document_chunks dc JOIN files f ON f.id = dc.file_id
       WHERE dc.user_id = :uid AND f.user_id = :uid AND f.status = 'ready'
         AND f.deleted_at IS NULL AND dc.file_id = ANY(:fids)
         AND dc.embedding IS NOT NULL AND dc.embedding_model = :model
    )
    SELECT id, 1 - (embedding <=> CAST(:q AS vector)) AS sim
      FROM scoped ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k
    """
)
FTS_SQL = text(
    """
    SELECT dc.id, ts_rank_cd(dc.content_tsv, q) AS rank
      FROM document_chunks dc JOIN files f ON f.id = dc.file_id,
           websearch_to_tsquery('simple', :q) q
     WHERE dc.user_id = :uid AND f.user_id = :uid AND f.status = 'ready'
       AND f.deleted_at IS NULL AND dc.file_id = ANY(:fids) AND dc.content_tsv @@ q
     ORDER BY rank DESC LIMIT :k
    """
)
FTS_ANY_SQL = text(
    """
    SELECT dc.id, ts_rank_cd(dc.content_tsv, q) AS rank
      FROM document_chunks dc JOIN files f ON f.id = dc.file_id,
           to_tsquery('simple', :q) q
     WHERE dc.user_id = :uid AND f.user_id = :uid AND f.status = 'ready'
       AND f.deleted_at IS NULL AND dc.file_id = ANY(:fids) AND dc.content_tsv @@ q
     ORDER BY rank DESC LIMIT :k
    """
)
CHUNKS_SQL = text(
    """
    SELECT dc.id, dc.file_id, dc.content, dc.token_count, dc.page_number, dc.sheet_name,
           dc.section_title, dc.chunk_index, f.original_filename,
           CASE WHEN :want_vec THEN dc.embedding::text ELSE NULL END AS emb
      FROM document_chunks dc JOIN files f ON f.id = dc.file_id
     WHERE dc.id = ANY(:ids) AND dc.user_id = :uid AND f.user_id = :uid
    """
)


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    file_id: uuid.UUID
    filename: str
    content: str
    page_number: int | None
    sheet_name: str | None
    section_title: str | None
    token_count: int
    score: float
    citation_index: int = 0

    def citation(self) -> dict[str, Any]:
        snippet = " ".join(strip_header(self.content).split())[:300]
        return {
            "index": self.citation_index,
            "source_type": "file",
            "file_id": str(self.file_id),
            "chunk_id": str(self.chunk_id),
            "filename": self.filename,
            "page_number": self.page_number,
            "sheet_name": self.sheet_name,
            "section_title": self.section_title,
            "snippet": snippet,
            "url": None,
            "title": None,
            "site_name": None,
            "published_at": None,
        }

    def render(self) -> str:
        loc = []
        if self.page_number:
            loc.append(f"page {self.page_number}")
        if self.sheet_name:
            loc.append(f'sheet "{self.sheet_name}"')
        if self.section_title:
            loc.append(f'section "{self.section_title}"')
        where = ", ".join(loc)
        return (
            f'[{self.citation_index}] source: "{self.filename}"'
            f"{', ' + where if where else ''}\n{strip_header(self.content)}"
        )


async def owned_ready_files(
    db: AsyncSession,
    user_id: uuid.UUID,
    file_ids: list[uuid.UUID] | None,
    conversation_id: uuid.UUID | None,
) -> list[uuid.UUID]:
    stmt = select(File.id).where(
        File.user_id == user_id,
        File.status == "ready",
        File.deleted_at.is_(None),
        File.kind == "document",
    )
    if conversation_id is not None and file_ids is None:
        stmt = stmt.join(ConversationFile, ConversationFile.file_id == File.id).where(
            ConversationFile.conversation_id == conversation_id
        )
    elif file_ids is not None:
        stmt = stmt.where(File.id.in_(file_ids))  # foreign ids silently dropped
    return list((await db.execute(stmt)).scalars().all())


def _fts_or_query(q: str) -> str:
    words = ["".join(ch for ch in w if ch.isalnum()) for w in q.lower().split()]
    words = [w for w in words if len(w) > 2][:12]
    return " | ".join(words)


def _parse_vec(s: str | None) -> list[float] | None:
    if not s:
        return None
    return [float(x) for x in s.strip("[]").split(",")]


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


async def retrieve(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    *,
    file_ids: list[uuid.UUID] | None = None,
    conversation_id: uuid.UUID | None = None,
    token_budget: int = 3000,
    max_chunks: int | None = None,
) -> list[RetrievedChunk]:
    s = get_settings()
    max_chunks = max_chunks or s.RAG_FINAL_MAX_CHUNKS
    scope = await owned_ready_files(db, user_id, file_ids, conversation_id)
    if not scope or not query.strip():
        return []
    emb = get_embeddings()
    qvec = await emb.embed_query(query) if emb.available() else None
    params = {"uid": user_id, "fids": scope}
    vec_rows: list[Any] = []
    if qvec is not None:
        await db.execute(text("SET LOCAL hnsw.ef_search = 100"))
        vec_rows = list(
            (
                await db.execute(
                    VEC_SQL,
                    {
                        **params,
                        "q": str(qvec),
                        "k": s.RAG_TOP_K_VECTOR,
                        "model": emb.model_name,
                    },
                )
            ).all()
        )
    fts_rows = list((await db.execute(FTS_SQL, {**params, "q": query, "k": s.RAG_TOP_K_FTS})).all())
    if not fts_rows and (orq := _fts_or_query(query)):
        fts_rows = list(
            (await db.execute(FTS_ANY_SQL, {**params, "q": orq, "k": s.RAG_TOP_K_FTS})).all()
        )
    # Reciprocal Rank Fusion (k=60)
    fused: dict[uuid.UUID, float] = {}
    sims = {r.id: float(r.sim) for r in vec_rows}
    fts_top = {r.id for r in fts_rows[:10]}
    for ranked in (vec_rows, fts_rows):
        for rank, r in enumerate(ranked):
            fused[r.id] = fused.get(r.id, 0.0) + 1 / (60 + rank + 1)
    candidates = [
        cid
        for cid in fused
        if cid in fts_top or sims.get(cid, 1.0 if not vec_rows else 0) >= s.RAG_SIM_THRESHOLD
    ]
    if not candidates:
        return []
    rows = {
        r.id: r
        for r in (
            await db.execute(
                CHUNKS_SQL, {"ids": candidates, "uid": user_id, "want_vec": qvec is not None}
            )
        ).all()
    }
    ordered = sorted((c for c in candidates if c in rows), key=lambda c: -fused[c])[:40]
    # MMR diversity when vectors exist; otherwise dedupe by (file, page).
    selected: list[uuid.UUID] = []
    vecs = {c: _parse_vec(rows[c].emb) for c in ordered} if qvec is not None else {}
    lam = s.RAG_MMR_LAMBDA
    pool = list(ordered)
    while pool and len(selected) < 12:

        def mmr(c: uuid.UUID) -> float:
            rel = fused[c]
            vc = vecs.get(c)
            if not selected or vc is None:
                return rel
            div = max(
                (_cos(vc, v) for sid in selected if (v := vecs.get(sid)) is not None), default=0.0
            )
            # RRF scores are ~1/60; scale cosine redundancy into the same range.
            return lam * rel - (1 - lam) * div / 60

        best = max(pool, key=mmr)
        pool.remove(best)
        selected.append(best)
    out: list[RetrievedChunk] = []
    used = 0
    for cid in selected:
        r = rows[cid]
        cost = estimate(strip_header(r.content)) + 20
        if used + cost > token_budget or len(out) >= max_chunks:
            continue
        used += cost
        out.append(
            RetrievedChunk(
                chunk_id=r.id,
                file_id=r.file_id,
                filename=r.original_filename,
                content=r.content,
                page_number=r.page_number,
                sheet_name=r.sheet_name,
                section_title=r.section_title,
                token_count=r.token_count,
                score=round(fused[cid], 5),
            )
        )
    for i, c in enumerate(out, start=1):
        c.citation_index = i
    log.info(
        "rag.retrieve",
        scope_files=len(scope),
        vec=len(vec_rows),
        fts=len(fts_rows),
        selected=len(out),
        semantic=qvec is not None,
    )
    return out


def render_block(chunks: list[RetrievedChunk]) -> str:
    from app.ai.prompts import neutralize

    body = "\n\n".join(neutralize(c.render()) for c in chunks)
    return f"<retrieved_documents>\n{body}\n</retrieved_documents>"


NO_MATCH_NOTE = (
    "The user's attached documents contain no passages relevant to this question. "
    "Say so rather than guessing, and answer from general knowledge only if you "
    "clearly label it as such."
)
