"""WebSearchService: provider abstraction, normalization, caching, extraction (docs/23)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
import structlog

from app.core.config import get_settings
from app.core.redis import get_redis, rkey
from app.search.fetcher import BlockedURL, safe_get

log = structlog.get_logger("app.search")
TRACKING = re.compile(r"^(utm_|gclid$|fbclid$|ref$|mc_)")


class SearchUnavailable(Exception):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    site_name: str
    published_at: str | None = None
    content: str | None = None


class WebSearchProvider(Protocol):
    name: str

    async def search(
        self, query: str, *, max_results: int, recency_days: int | None
    ) -> list[SearchResult]: ...


def _time_range(days: int | None) -> str | None:
    if days is None:
        return None
    return (
        "day"
        if days <= 1
        else "week"
        if days <= 7
        else "month"
        if days <= 31
        else "year"
        if days <= 366
        else None
    )


class SearxngProvider:
    """Self-hosted SearXNG JSON API (format=json must be enabled in settings.yml)."""

    name = "searxng"

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    async def search(
        self, query: str, *, max_results: int, recency_days: int | None
    ) -> list[SearchResult]:
        params = {"q": query, "format": "json", "safesearch": "1", "language": "en"}
        if tr := _time_range(recency_days):
            params["time_range"] = tr
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.base}/search", params=params)
            r.raise_for_status()
            data = r.json()
        return [
            SearchResult(
                x.get("title", ""),
                x.get("url", ""),
                x.get("content", ""),
                "",
                x.get("publishedDate"),
            )
            for x in data.get("results", [])
        ]


class BraveProvider:
    """Brave Search API (verify endpoint/params against current Brave docs)."""

    name = "brave"

    def __init__(self, key: str) -> None:
        self.key = key

    async def search(
        self, query: str, *, max_results: int, recency_days: int | None
    ) -> list[SearchResult]:
        params: dict[str, str | int] = {
            "q": query,
            "count": max(max_results, 10),
            "safesearch": "moderate",
        }
        fresh = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}.get(
            _time_range(recency_days) or ""
        )
        if fresh:
            params["freshness"] = fresh
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://api.search.brave.com/res/v1/web/search",
                params=params,
                headers={"X-Subscription-Token": self.key, "Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
        return [
            SearchResult(
                x.get("title", ""),
                x.get("url", ""),
                x.get("description", ""),
                (x.get("profile") or {}).get("name", ""),
                x.get("age"),
            )
            for x in (data.get("web") or {}).get("results", [])
        ]


def provider() -> WebSearchProvider | None:
    s = get_settings()
    if s.WEB_SEARCH_PROVIDER == "searxng" and s.SEARXNG_URL:
        return SearxngProvider(s.SEARXNG_URL)
    if s.WEB_SEARCH_PROVIDER == "brave" and s.BRAVE_SEARCH_API_KEY:
        return BraveProvider(s.BRAVE_SEARCH_API_KEY.get_secret_value())
    return None


def _strip_html(s: str) -> str:
    import html

    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k)])
    return urlunsplit((p.scheme, p.netloc.lower(), p.path, q, ""))


def normalize(results: list[SearchResult], max_results: int) -> list[SearchResult]:
    out, seen = [], set()
    for r in results:
        if not r.url.startswith(("http://", "https://")):
            continue
        host = urlsplit(r.url).hostname or ""
        if re.fullmatch(r"[\d.]+|\[.*\]", host):
            continue
        url = canonical_url(r.url)
        key = (url, (r.title or "").lower().strip())
        if url in seen or key in seen:
            continue
        seen.update({url, key})
        out.append(
            SearchResult(
                _strip_html(r.title)[:200],
                url,
                _strip_html(r.snippet)[:400],
                r.site_name or host.removeprefix("www."),
                r.published_at,
            )
        )
        if len(out) >= max_results:
            break
    return out


def _extract_main(html_text: str) -> str | None:
    import trafilatura

    text = trafilatura.extract(
        html_text, include_comments=False, include_tables=True, favor_precision=True
    )
    return text if text and len(text) >= 200 else None


async def _fetch_content(r: SearchResult) -> None:
    key = rkey("wp", hashlib.sha256(r.url.encode()).hexdigest())
    try:
        if cached := await get_redis().get(key):
            r.content = cached
            return
    except Exception:
        pass
    try:
        page = await safe_get(r.url)
    except (BlockedURL, httpx.HTTPError, UnicodeError):
        return
    text = (
        await asyncio.to_thread(_extract_main, page.text)
        if page.content_type != "text/plain"
        else page.text
    )
    if text:
        r.content = text[:4800]
        try:
            await get_redis().set(key, r.content, ex=6 * 3600)
        except Exception:
            pass


async def search(
    query: str, *, max_results: int = 5, recency_days: int | None = None
) -> list[SearchResult]:
    prov = provider()
    if prov is None:
        raise SearchUnavailable("no provider configured")
    query = " ".join(query.strip().strip("\"'").split())[:300]
    key = rkey(
        "ws",
        prov.name,
        hashlib.sha256(f"{query}|{recency_days}|{max_results}".encode()).hexdigest(),
    )
    try:
        if cached := await get_redis().get(key):
            return [SearchResult(**x) for x in json.loads(cached)]
    except Exception:
        pass
    raw: list[SearchResult] = []
    for attempt in range(2):
        try:
            raw = await prov.search(query, max_results=max_results, recency_days=recency_days)
            break
        except (httpx.HTTPError, ValueError) as e:
            if attempt == 1:
                raise SearchUnavailable(str(e)) from e
            await asyncio.sleep(0.5)
    results = normalize(raw, max_results)
    await asyncio.wait(
        [asyncio.create_task(_fetch_content(r)) for r in results[:3]], timeout=8
    ) if results else None
    try:
        await get_redis().set(
            key,
            json.dumps([asdict(r) for r in results]),
            ex=900 if (recency_days or 99) <= 1 else 3600,
        )
    except Exception:
        pass
    return results
