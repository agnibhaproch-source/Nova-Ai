"""process_file: validate → scan → extract → normalize → chunk → embed → index (docs/19 §1).

Idempotent: every run replaces the file's chunks. CPU-bound parsing runs in a process pool.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import tempfile
import uuid
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import delete, insert, update

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.documents.chunker import chunk
from app.documents.extract import Extraction, ExtractionError, extract
from app.embeddings.service import EmbeddingUnavailable, get_embeddings
from app.files import scanner, storage
from app.files.validation import FileRejected, verify_content
from app.models import DocumentChunk, File, ModerationFlag
from app.services import quota_service

log = structlog.get_logger("app.documents")
_pool: ProcessPoolExecutor | None = None
MESSAGES = {
    "EXTRACTION_FAILED": "We couldn't read this document.",
    "EMBEDDING_UNAVAILABLE": "Indexing is temporarily unavailable. Try again shortly.",
    "SCAN_UNAVAILABLE": "Security scanning is temporarily unavailable.",
    "FILE_MALWARE_DETECTED": "This file was blocked by our security scan.",
}


def _executor() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=get_settings().WORKER_EXTRACT_PROCESSES)
    return _pool


def _extract_in_child(path: str, ext: str, filename: str, max_pages: int) -> Extraction:
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    except (ValueError, OSError):
        pass
    return extract(Path(path), ext, filename, max_pages)


async def _stage(file_id: uuid.UUID, stage: str, progress: int, **values: Any) -> None:
    async with get_sessionmaker()() as db:
        f = await db.get(File, file_id)
        if f is None:
            return
        f.metadata_ = {**(f.metadata_ or {}), "stage": stage, "progress": progress}
        for k, v in values.items():
            setattr(f, k, v)
        await db.commit()


async def _finish(
    file_id: uuid.UUID,
    status: str,
    code: str | None = None,
    message: str | None = None,
    **values: Any,
) -> None:
    async with get_sessionmaker()() as db:
        await db.execute(
            update(File)
            .where(File.id == file_id, File.status != "deleted")
            .values(
                status=status,
                error_code=code,
                error_message=message,
                processed_at=datetime.now(UTC),
                **values,
            )
        )
        await db.commit()


def _derive_image(path: Path) -> tuple[bytes, bytes, dict[str, int]]:
    """Display (WEBP ≤2048px) and model (JPEG ≤1568px) derivatives; re-encoding strips EXIF."""
    from PIL import Image, ImageOps

    with Image.open(path) as src:
        im = ImageOps.exif_transpose(src).convert("RGB")
        display = im.copy()
        display.thumbnail((2048, 2048))
        buf = io.BytesIO()
        display.save(buf, "WEBP", quality=85)
        model = im.copy()
        model.thumbnail((1568, 1568))
        mbuf = io.BytesIO()
        model.save(mbuf, "JPEG", quality=85)
        return buf.getvalue(), mbuf.getvalue(), {"width": im.width, "height": im.height}


async def process_file(file_id: uuid.UUID) -> None:
    sm = get_sessionmaker()
    async with sm() as db:
        f = await db.get(File, file_id)
        if f is None or f.status in ("deleted", "rejected"):
            return
        user_id, key, ext, name, kind = (
            f.user_id,
            f.storage_key,
            f.extension,
            f.original_filename,
            f.kind,
        )
        from app.models import User

        user = await db.get(User, user_id)
        limits = await quota_service.plan_limits(db, user.plan_key if user else "free")
    with tempfile.TemporaryDirectory(prefix="nova-file-") as tmp:
        path = Path(tmp) / f"src.{ext}"
        await _stage(file_id, "validating", 5, status="scanning")
        await storage.download_to(key, path)
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            detected = verify_content(path, ext)
        except FileRejected as e:
            await _finish(file_id, "rejected", e.code, e.message, sha256=sha)
            await storage.delete_prefix(key)
            return
        if get_settings().CLAMAV_ENABLED:
            await _stage(file_id, "scanning", 15)
            try:
                found = await scanner.scan(path)
            except scanner.ScanUnavailable:
                raise  # ARQ retries with backoff; never mark ready unscanned
            if found:
                await _finish(
                    file_id,
                    "rejected",
                    "FILE_MALWARE_DETECTED",
                    MESSAGES["FILE_MALWARE_DETECTED"],
                    sha256=sha,
                )
                await storage.delete_prefix(key)
                async with sm() as db:
                    db.add(
                        ModerationFlag(
                            user_id=user_id,
                            source="automated",
                            category="abuse",
                            details=f"malware upload: {found}"[:2000],
                        )
                    )
                    await db.commit()
                return
        if kind == "image":
            data, model_jpg, dims = await asyncio.to_thread(_derive_image, path)
            await storage.put(f"{key}/derived/display.webp", data, "image/webp")
            await storage.put(f"{key}/derived/model.jpg", model_jpg, "image/jpeg")
            await _finish(
                file_id,
                "ready",
                sha256=sha,
                detected_mime_type=detected,
                metadata_={"stage": "done", "progress": 100, **dims},
            )
            return

        await _stage(
            file_id, "extracting", 30, status="processing", sha256=sha, detected_mime_type=detected
        )
        try:
            loop = asyncio.get_running_loop()
            ex = await asyncio.wait_for(
                loop.run_in_executor(
                    _executor(),
                    _extract_in_child,
                    str(path),
                    ext,
                    name,
                    int(limits.get("max_pages_per_file", 100)),
                ),
                300,
            )
        except ExtractionError as e:
            await _finish(file_id, "failed", e.code, e.message)
            return
        except Exception:
            log.exception("file.extraction_failed", file_id=str(file_id), extension=ext)
            await _finish(file_id, "failed", "EXTRACTION_FAILED", MESSAGES["EXTRACTION_FAILED"])
            return

    await _stage(file_id, "chunking", 55)
    chunks = chunk(ex.segments, name)
    max_tokens = int(limits.get("max_extracted_tokens_per_file", 200_000))
    total, kept = 0, []
    for c in chunks:
        total += c.token_count
        if total > max_tokens:
            ex.warnings.append("truncated_tokens")
            break
        kept.append(c)
    if not kept:
        await _finish(file_id, "failed", "NO_EXTRACTABLE_TEXT", "We couldn't find any text.")
        return

    emb = get_embeddings()
    vectors: list[list[float]] | None = None
    if emb.available():
        await _stage(file_id, "embedding", 70)
        try:
            vectors = await emb.embed_documents([c.content for c in kept])
        except EmbeddingUnavailable as e:
            if "DIMENSION" in str(e):
                await _finish(
                    file_id, "failed", "EMBEDDING_DIMENSION_MISMATCH", MESSAGES["EXTRACTION_FAILED"]
                )
                return
            raise  # retried by ARQ
    await _stage(file_id, "indexing", 90)
    async with sm() as db:
        await db.execute(delete(DocumentChunk).where(DocumentChunk.file_id == file_id))
        rows = [
            {
                "file_id": file_id,
                "user_id": user_id,
                "chunk_index": c.index,
                "content": c.content,
                "token_count": c.token_count,
                "page_number": c.page_number,
                "sheet_name": (c.sheet_name or "")[:128] or None,
                "section_title": c.section_title,
                "char_start": c.char_start,
                "char_end": c.char_end,
                "embedding": vectors[i] if vectors else None,
                "embedding_model": emb.model_name if vectors else None,
            }
            for i, c in enumerate(kept)
        ]
        for i in range(0, len(rows), 200):
            await db.execute(insert(DocumentChunk), rows[i : i + 200])
        await db.execute(
            update(File)
            .where(File.id == file_id, File.status != "deleted")
            .values(
                status="ready",
                chunk_count=len(kept),
                token_count=sum(c.token_count for c in kept),
                page_count=ex.page_count,
                processed_at=datetime.now(UTC),
                error_code=None,
                error_message=None,
                metadata_={
                    **ex.metadata,
                    "stage": "done",
                    "progress": 100,
                    "warnings": ex.warnings,
                    "semantic_index": bool(vectors),
                },
            )
        )
        await db.commit()
    log.info(
        "file.processing.completed",
        file_id=str(file_id),
        extension=ext,
        chunks=len(kept),
        semantic=bool(vectors),
    )
