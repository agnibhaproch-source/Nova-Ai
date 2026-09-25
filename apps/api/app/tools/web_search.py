"""web_search tool with numbered, citable sources (docs/23)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import Field

from app.search import service as search
from app.services.memory_service import contains_secret
from app.tools.base import Tool, ToolArgs, ToolContext, ToolError, ToolResult


class WebSearchTool(Tool):
    name = "web_search"
    display_name = "Web search"
    description = (
        "Search the web for current information. Write a concise search engine query "
        "(max 12 words) with the key entities; add the year for time-sensitive "
        "questions. Returns numbered sources you must cite as [n]."
    )
    timeout_seconds = 20.0
    requires_preference = "web_search_enabled"

    class Args(ToolArgs):
        query: str = Field(min_length=1, max_length=300)
        recency_days: int | None = Field(default=None, ge=1, le=3650)
        max_results: int = Field(default=5, ge=1, le=8)

    def label(self, args: Any) -> str:
        return f"Searching the web for “{args.query[:60]}”"

    async def run(self, args: Any, ctx: ToolContext) -> ToolResult:
        if contains_secret(args.query):
            raise ToolError("TOOL_NOT_ALLOWED", "The query contained sensitive data.")
        try:
            results = await search.search(
                args.query, max_results=args.max_results, recency_days=args.recency_days
            )
        except search.SearchUnavailable as e:
            raise ToolError(
                "SEARCH_UNAVAILABLE",
                "Web search is temporarily unavailable. Say so; don't guess current facts.",
            ) from e
        cites, items = [], []
        for n, r in enumerate(results, start=ctx.citation_offset + 1):
            items.append(
                {
                    "n": n,
                    "title": r.title,
                    "url": r.url,
                    "site": r.site_name,
                    "published": r.published_at,
                    "snippet": r.snippet,
                    "content": r.content,
                }
            )
            cites.append(
                {
                    "index": n,
                    "source_type": "web",
                    "url": r.url,
                    "title": r.title,
                    "site_name": r.site_name,
                    "published_at": r.published_at,
                    "snippet": r.snippet[:300],
                    "file_id": None,
                    "chunk_id": None,
                    "filename": None,
                    "page_number": None,
                    "sheet_name": None,
                    "section_title": None,
                }
            )
        content = {
            "tool": "web_search",
            "untrusted_content": True,
            "query": args.query,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "results": items,
        }
        return ToolResult(
            "succeeded",
            json.dumps(content),
            f"Found {len(results)} results for “{args.query}”",
            display={
                "query": args.query,
                "results": [
                    {"n": i["n"], "title": i["title"], "url": i["url"], "site": i["site"]}
                    for i in items
                ],
            },
            citations=cites,
        )
