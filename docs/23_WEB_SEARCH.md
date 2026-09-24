# 23 — Web Search

Web search is implemented **only as a tool** (`web_search`) invoked by the model through the tool loop (`22_TOOL_SYSTEM.md`). There is no separate "search mode" pipeline; the composer's globe toggle simply enables/disables the tool for the turn (and when enabled explicitly by the user for a turn, the system prompt adds "The user wants you to search the web for this request.").

## 1. Flow

```
model → web_search{query, recency_days?, max_results?}
  → ToolEngine (authorize, quota, validate)
  → WebSearchService.search(query, opts)
       ├─ cache lookup (Redis)
       ├─ provider.search() → SearchResult[]
       ├─ normalize + dedupe + filter
       ├─ fetch & extract top N pages (SafeFetcher + trafilatura), in parallel
       └─ build ToolResult (model_content with numbered sources, display, citations)
  → model answers citing [n]
```

## 2. Query generation

- The model writes the query as the tool argument. The tool description instructs: "Write a concise search engine query (≤ 12 words) containing the key entities; add the year for time-sensitive questions."
- Server-side normalization: trim, collapse whitespace, strip surrounding quotes, max 300 chars; reject empty.
- Queries containing obvious secrets (same `SensitiveContentFilter` as memory) are blocked (`TOOL_NOT_ALLOWED` with "query contained sensitive data").
- Only the query string leaves our system; no user identifiers are sent to the provider.

## 3. Provider abstraction (`app/search/providers/base.py`)

```python
class SearchResult(BaseModel):
    title: str
    url: HttpUrl
    snippet: str
    site_name: str | None
    published_at: datetime | None
    rank: int

class WebSearchProvider(Protocol):
    name: str
    async def search(self, query: str, *, max_results: int, recency_days: int | None,
                     locale: str, safe_search: bool) -> list[SearchResult]: ...
```

Adapters (selected by `WEB_SEARCH_PROVIDER`):

| Value | Adapter | Config | Notes |
|---|---|---|---|
| `searxng` | `SearxngProvider` | `SEARXNG_URL` | Self-hosted; `GET {SEARXNG_URL}/search?q=&format=json&language=&time_range=&safesearch=1` (JSON format must be enabled in `settings.yml`); verify params against the deployed version |
| `brave` | `BraveSearchProvider` | `BRAVE_SEARCH_API_KEY` | Brave Search API web endpoint with `X-Subscription-Token` header; verify endpoint/params against Brave docs |
| `none` | — | — | Tool not registered |

Recency mapping: `recency_days ≤ 1 → day`, `≤ 7 → week`, `≤ 31 → month`, `≤ 366 → year`, else none. Safe search is always on (moderate).

Adding a provider = new adapter + docs update; no other code changes.

## 4. Result normalization

1. Drop results with non-http(s) URLs, IP-literal hosts, or hosts in the blocklist (`system_settings.web_search_blocked_domains`).
2. Canonicalize URL: lower-case host, remove fragments and tracking params (`utm_*`, `gclid`, `fbclid`, `ref`).
3. Dedupe by canonical URL and by `(site, normalized title)`.
4. `site_name` from provider or derived from host (strip `www.`).
5. Truncate `title` to 200 chars, `snippet` to 400 chars; strip HTML tags/entities from both.
6. Keep top `max_results` (default 5, max 8).

## 5. Content extraction

- For the top `min(3, n)` results, fetch the page via `SafeFetcher` (`33_SECURITY.md` §7) in parallel with a 5 s per-request timeout, 2 MB max body, `Accept: text/html`, User-Agent `NovaAI-Bot/1.0 (+{APP_URL}/bot)`, respecting `robots.txt` (cached 24 h per host; disallowed → snippet only).
- Only `text/html` and `text/plain` are processed; others skipped.
- Extract main text with `trafilatura.extract(html, include_comments=False, include_tables=True, favor_precision=True)`; fall back to snippet if extraction returns < 200 chars.
- Truncate each page's extracted text to ~1,200 tokens (head-biased: first 70% + last 30% of the budget split).
- Total extraction wall time budget: 8 s; unfinished fetches are cancelled and their snippets used.

## 6. Tool result format

`model_content` (JSON, compact):

```json
{"tool":"web_search","untrusted_content":true,"query":"...","retrieved_at":"2026-09-24T10:00:00Z",
 "results":[{"n":3,"title":"...","url":"https://...","site":"example.com","published":"2026-09-01",
             "snippet":"...","content":"<extracted text or null>"}]}
```

`n` values continue after any RAG citation indices already assigned in this message (unified numbering, `20_RAG_SYSTEM.md` §8).

`display`: `{"query": str, "results": [{"n","title","url","site","favicon_url"}]}` — favicon via `https://{host}/favicon.ico` is **not** fetched by our server; the UI shows a generic globe icon plus site name (avoids third-party requests from the browser per privacy policy).

## 7. Source metadata and citations

Each result becomes a `CitationSource(source_type="web", index=n, url, title, site_name, published_at, snippet)`. Citation parts are created only for indices the model actually cites. UI popover shows title, site, date, snippet, and an external link (`target="_blank" rel="noopener noreferrer nofollow"`).

## 8. Failures

| Failure | Behavior |
|---|---|
| Provider timeout (10 s) / 5xx | Retry once after 500 ms; then `failed` `SEARCH_UNAVAILABLE`; model told "Web search is temporarily unavailable" and must say so rather than guessing current facts |
| Provider 429 | `failed` `SEARCH_RATE_LIMITED`; circuit opens 60 s |
| Zero results | `succeeded` with empty results; model told "No results." |
| All page fetches fail | Use snippets only |

## 9. Rate limiting and quotas

- Per user: plan daily quota (`web_search_per_day`) + 10/min burst limit (`tool_web_search` policy).
- Global: provider protection limit `WEB_SEARCH_GLOBAL_RPS` (default 10 req/s) via Redis GCRA key `nova:{env}:rl:global:web_search`; exceeding → queue up to 2 s then `SEARCH_RATE_LIMITED`.

## 10. Caching

- Search results: key `nova:{env}:ws:{provider}:{sha256(normalized_query|recency|locale|max_results)}`, TTL 1 h (15 min when `recency_days ≤ 1`).
- Extracted page content: key `nova:{env}:wp:{sha256(canonical_url)}`, TTL 6 h, max 64 KB stored.
- Cache is shared across users (queries are not personal data once normalized; the cache key is a hash). Users' search history is not stored beyond `tool_calls.arguments` (owned by the user).

## 11. Observability

Span `tool.web_search` with children `search.provider`, `search.fetch` (per URL host only, no path). Metrics: `nova_web_search_requests_total{provider,status}`, `nova_web_search_cache_hits_total`, `nova_web_fetch_total{status}`.
