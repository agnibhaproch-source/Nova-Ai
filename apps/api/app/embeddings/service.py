"""EmbeddingService: independent of Groq; self-hosted TEI in production (docs/21 §1).

If no embedding model is configured, `available()` is False and RAG runs in FTS-only mode
(docs/48 F11) — nothing is simulated.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal, Protocol

import httpx
import structlog

from app.core.config import get_settings
from app.core.redis import get_redis, rkey

log = structlog.get_logger()


class EmbeddingUnavailable(Exception):
    pass


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    async def embed(
        self, texts: list[str], *, input_type: Literal["document", "query"]
    ) -> list[list[float]]: ...


class TEIEmbeddingProvider:
    """Hugging Face Text Embeddings Inference: POST {endpoint}/embed {"inputs": [...]}."""

    def __init__(self, endpoint: str, model: str, dim: int, api_key: str | None) -> None:
        self.model_name, self.dimensions = model, dim
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=endpoint.rstrip("/"), headers=headers, timeout=httpx.Timeout(30.0, connect=3.0)
        )

    async def embed(
        self, texts: list[str], *, input_type: Literal["document", "query"]
    ) -> list[list[float]]:
        s = get_settings()
        prefix = s.EMBEDDING_QUERY_PREFIX if input_type == "query" else s.EMBEDDING_DOCUMENT_PREFIX
        payload = {"inputs": [prefix + t for t in texts], "truncate": True, "normalize": True}
        for attempt in range(3):
            try:
                r = await self._client.post("/embed", json=payload)
                r.raise_for_status()
                return [list(map(float, v)) for v in r.json()]
            except (httpx.HTTPError, ValueError) as e:
                if attempt == 2:
                    raise EmbeddingUnavailable(str(e)) from e
                import asyncio

                await asyncio.sleep(2**attempt)
        raise EmbeddingUnavailable("unreachable")


class HashEmbeddingProvider:
    """TEST-ONLY deterministic bag-of-words hashing (refused outside APP_ENV=test)."""

    def __init__(self, dim: int) -> None:
        self.model_name, self.dimensions = "test-hash-embedding", dim

    async def embed(
        self, texts: list[str], *, input_type: Literal["document", "query"]
    ) -> list[list[float]]:
        out = []
        for t in texts:
            v = [0.0] * self.dimensions
            for w in t.lower().split():
                w = "".join(ch for ch in w if ch.isalnum())
                if w:
                    v[int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dimensions] += 1.0
            out.append(v)
        return out


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class EmbeddingService:
    def __init__(self) -> None:
        s = get_settings()
        self.provider: EmbeddingProvider | None = None
        if s.EMBEDDING_PROVIDER == "hash":
            if s.APP_ENV != "test":
                raise RuntimeError("EMBEDDING_PROVIDER=hash is allowed only in APP_ENV=test")
            self.provider = HashEmbeddingProvider(s.EMBEDDING_DIMENSIONS or 384)
        elif s.EMBEDDING_ENDPOINT and s.EMBEDDING_MODEL and s.EMBEDDING_DIMENSIONS:
            key = s.EMBEDDING_API_KEY.get_secret_value() if s.EMBEDDING_API_KEY else None
            self.provider = TEIEmbeddingProvider(
                s.EMBEDDING_ENDPOINT, s.EMBEDDING_MODEL, s.EMBEDDING_DIMENSIONS, key
            )

    def available(self) -> bool:
        return self.provider is not None

    @property
    def model_name(self) -> str | None:
        return self.provider.model_name if self.provider else None

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self.provider:
            raise EmbeddingUnavailable("no embedding model configured")
        size = get_settings().EMBEDDING_BATCH_SIZE
        out: list[list[float]] = []
        for i in range(0, len(texts), size):
            vecs = await self.provider.embed(texts[i : i + size], input_type="document")
            for v in vecs:
                if len(v) != self.provider.dimensions:
                    raise EmbeddingUnavailable("EMBEDDING_DIMENSION_MISMATCH")
                out.append(_normalize(v))
        return out

    async def embed_query(self, text: str) -> list[float] | None:
        """Returns None when embeddings are unavailable (callers degrade to FTS)."""
        if not self.provider:
            return None
        key = rkey(
            "emb", "q", hashlib.sha256(f"{self.provider.model_name}|{text}".encode()).hexdigest()
        )
        try:
            cached = await get_redis().get(key)
            if cached:
                return list(json.loads(cached))
        except Exception:
            pass
        try:
            vec = _normalize((await self.provider.embed([text], input_type="query"))[0])
        except EmbeddingUnavailable:
            log.warning("embeddings.query_failed")
            return None
        try:
            await get_redis().set(key, json.dumps(vec), ex=86400)
        except Exception:
            pass
        return vec


_service: EmbeddingService | None = None


def get_embeddings() -> EmbeddingService:
    global _service
    if _service is None:
        _service = EmbeddingService()
    return _service


def reset_embeddings() -> None:
    global _service
    _service = None
