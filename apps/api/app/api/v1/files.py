"""/files, /conversations/{id}/files, /rag/search (docs/31 §7–8)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import RedirectResponse
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, rate_limit, require_csrf, require_scopes
from app.db.session import get_db
from app.schemas.common import Envelope, In, ListEnvelope
from app.services import file_service, rag_service

router = APIRouter(tags=["files"])


class InitiateIn(In):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0, le=50 * 1024 * 1024)
    mime_type: str = Field(min_length=3, max_length=127)
    purpose: Literal["attachment", "avatar"] = "attachment"
    conversation_id: uuid.UUID | None = None


class AttachIn(In):
    file_id: uuid.UUID


class RagSearchIn(In):
    query: str = Field(min_length=1, max_length=1000)
    file_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    conversation_id: uuid.UUID | None = None
    top_k: int = Field(default=8, ge=1, le=20)


@router.post(
    "/files",
    status_code=status.HTTP_201_CREATED,
    operation_id="files_initiate",
    dependencies=[Depends(rate_limit("file_upload"))],
)
async def initiate(
    body: InitiateIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("files:write")),
) -> Envelope[dict[str, Any]]:
    return Envelope(
        data=await file_service.initiate(
            db,
            p,
            filename=body.filename,
            size_bytes=body.size_bytes,
            mime_type=body.mime_type,
            purpose=body.purpose,
            conversation_id=body.conversation_id,
        )
    )


@router.post(
    "/files/{file_id}/complete",
    operation_id="files_complete",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def complete(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("files:write")),
) -> Envelope[dict[str, Any]]:
    return Envelope(data=file_service.file_out(await file_service.complete(db, p, file_id)))


@router.get("/files", operation_id="files_list", dependencies=[Depends(rate_limit("api_read"))])
async def list_files(
    kind: Literal["document", "image"] | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("files:read")),
) -> ListEnvelope[dict[str, Any]]:
    rows = await file_service.list_files(db, p.uid, kind=kind, q=q, limit=limit)
    return ListEnvelope(data=[file_service.file_out(f) for f in rows])


@router.get(
    "/files/{file_id}", operation_id="files_get", dependencies=[Depends(rate_limit("api_read"))]
)
async def get_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("files:read")),
) -> Envelope[dict[str, Any]]:
    return Envelope(data=file_service.file_out(await file_service.get_owned(db, p.uid, file_id)))


@router.get(
    "/files/{file_id}/download",
    operation_id="files_download",
    dependencies=[Depends(rate_limit("api_read"))],
)
async def download(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("files:read")),
) -> RedirectResponse:
    return RedirectResponse(await file_service.download_url(db, p.uid, file_id), status_code=302)


@router.get(
    "/files/{file_id}/content-url",
    operation_id="files_content_url",
    dependencies=[Depends(rate_limit("api_read"))],
)
async def content_url(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("files:read")),
) -> Envelope[dict[str, str]]:
    f = await file_service.get_owned(db, p.uid, file_id)
    from app.core.errors import AppError, ErrorCode
    from app.files import storage

    if f.kind != "image" or f.status != "ready":
        raise AppError(ErrorCode.INVALID_FILE)
    url = await storage.presigned_get(f"{f.storage_key}/derived/display.webp", expires=3600)
    return Envelope(data={"url": url})


@router.post(
    "/files/{file_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="files_retry",
    dependencies=[Depends(rate_limit("file_upload"))],
)
async def retry(
    file_id: uuid.UUID, db: AsyncSession = Depends(get_db), p: Principal = Depends(require_csrf)
) -> Envelope[dict[str, Any]]:
    return Envelope(data=file_service.file_out(await file_service.retry(db, p.uid, file_id)))


@router.delete(
    "/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="files_delete",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def delete_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("files:write")),
) -> Response:
    await file_service.soft_delete(db, p.uid, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/conversations/{conversation_id}/files",
    operation_id="conversation_files_list",
    dependencies=[Depends(rate_limit("api_read"))],
)
async def conv_files(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_scopes("files:read")),
) -> ListEnvelope[dict[str, Any]]:
    rows = await file_service.conversation_files(db, p.uid, conversation_id)
    return ListEnvelope(data=[file_service.file_out(f) for f in rows])


@router.post(
    "/conversations/{conversation_id}/files",
    status_code=status.HTTP_201_CREATED,
    operation_id="conversation_files_attach",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def attach(
    conversation_id: uuid.UUID,
    body: AttachIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("files:write")),
) -> Envelope[dict[str, Any]]:
    f = await file_service.attach(db, p.uid, conversation_id, body.file_id)
    await db.commit()
    return Envelope(data=file_service.file_out(f))


@router.delete(
    "/conversations/{conversation_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="conversation_files_detach",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def detach(
    conversation_id: uuid.UUID,
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Response:
    await file_service.detach(db, p.uid, conversation_id, file_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/rag/search", operation_id="rag_search", dependencies=[Depends(rate_limit("rag_search"))]
)
async def rag_search(
    body: RagSearchIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _s: Principal = Depends(require_scopes("files:read")),
) -> ListEnvelope[dict[str, Any]]:
    chunks = await rag_service.retrieve(
        db,
        p.uid,
        body.query,
        file_ids=body.file_ids,
        conversation_id=body.conversation_id,
        token_budget=8000,
        max_chunks=body.top_k,
    )
    return ListEnvelope(
        data=[
            {
                "chunk_id": str(c.chunk_id),
                "file_id": str(c.file_id),
                "filename": c.filename,
                "page_number": c.page_number,
                "sheet_name": c.sheet_name,
                "section_title": c.section_title,
                "content": c.render(),
                "score": c.score,
            }
            for c in chunks
        ]
    )
