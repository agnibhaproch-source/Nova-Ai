"""file_search: RAG over the user's own files, permission-filtered (docs/22 §11.2)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import Field

from app.db.session import get_sessionmaker
from app.services import rag_service
from app.tools.base import Tool, ToolArgs, ToolContext, ToolResult


class FileSearchTool(Tool):
    name = "file_search"
    display_name = "File search"
    description = (
        "Search the user's uploaded documents for passages relevant to a query. "
        "Returns numbered excerpts you can cite as [n]."
    )
    timeout_seconds = 8.0

    class Args(ToolArgs):
        query: str = Field(min_length=1, max_length=500)
        file_ids: list[str] | None = Field(default=None, max_length=20)
        top_k: int = Field(default=6, ge=1, le=10)

    def label(self, args: Any) -> str:
        return f"Searching your files for “{args.query[:60]}”"

    async def run(self, args: Any, ctx: ToolContext) -> ToolResult:
        ids: list[uuid.UUID] | None = None
        if args.file_ids:
            ids = []
            for f in args.file_ids:
                try:
                    ids.append(uuid.UUID(f))
                except ValueError:
                    continue
        async with get_sessionmaker()() as db:
            chunks = await rag_service.retrieve(
                db, ctx.user_id, args.query, file_ids=ids, token_budget=3500, max_chunks=args.top_k
            )
        cites = []
        for i, c in enumerate(chunks, start=ctx.citation_offset + 1):
            c.citation_index = i
            cites.append(c.citation())
        content = {
            "tool": "file_search",
            "untrusted_content": True,
            "query": args.query,
            "results": [
                {
                    "n": c.citation_index,
                    "source": c.filename,
                    "page": c.page_number,
                    "text": c.render(),
                }
                for c in chunks
            ],
        }
        summary = f"Found {len(chunks)} passage{'s' if len(chunks) != 1 else ''}"
        return ToolResult(
            "succeeded",
            json.dumps(content),
            summary,
            citations=cites,
            display={
                "query": args.query,
                "results": [
                    {"n": c.citation_index, "filename": c.filename, "page": c.page_number}
                    for c in chunks
                ],
            },
        )
