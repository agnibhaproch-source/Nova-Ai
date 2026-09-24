# 22 — Tool System

## 1. Principles

- The model can only **request** tool calls. The server decides whether, how, and with what limits to execute them.
- Only tools registered in `ToolRegistry` exist. There is no reflection, `getattr`, dynamic import, or generic "call function by name" path into application code.
- Every tool call is validated, authorized, rate-limited, time-boxed, persisted, observable, and shown to the user.

## 2. Tool interface (`app/tools/base.py`)

```python
class ToolContext(BaseModel):
    user_id: UUID
    conversation_id: UUID
    message_id: UUID
    request_id: str
    plan_key: str
    preferences: UserPreferences
    attached_file_ids: list[UUID]
    cancel_event: asyncio.Event          # arbitrary_types_allowed

class ToolResult(BaseModel):
    status: Literal["succeeded", "failed", "timed_out", "denied"]
    model_content: str                  # what is sent back to Groq as the tool message (≤ 4,000 tokens after fitting)
    display: dict                       # UI payload (sanitized)
    summary: str                        # ≤ 500 chars, human-readable ("Found 5 results for …")
    citations: list[CitationSource] = []  # web/file sources to register for [n] mapping
    code_part: CodePartData | None = None # for code_execution
    error_code: str | None = None

class Tool(Protocol):
    name: str                           # ^[a-z][a-z0-9_]{2,40}$
    description: str                    # shown to the model
    parameters_model: type[BaseModel]   # Pydantic model → JSON schema
    timeout_seconds: float
    quota_key: str | None               # e.g. "web_search_per_day"
    requires_preference: str | None     # e.g. "web_search_enabled"
    plans: frozenset[str]
    def label(self, args: BaseModel) -> str          # "Searching the web for …"
    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult
```

## 3. Registry (`app/tools/registry.py`)

```python
class ToolRegistry:
    def __init__(self, tools: list[Tool]): ...          # constructed once at startup from an explicit list
    def get(self, name: str) -> Tool | None
    def available_for(self, ctx: ToolContext, model: ModelConfig, turn_toggles: ToolToggles | None) -> list[Tool]
    def schemas_for(self, tools: list[Tool]) -> list[ToolSchema]
```

Initial explicit registration in `app/tools/__init__.py`:

```python
def build_registry(deps) -> ToolRegistry:
    tools: list[Tool] = [CalculatorTool(), FileSearchTool(deps.rag)]
    if deps.settings.WEB_SEARCH_PROVIDER != "none":
        tools.append(WebSearchTool(deps.web_search))
    if deps.settings.SANDBOX_RUNNER_URL:
        tools.append(CodeExecutionTool(deps.sandbox))
    return ToolRegistry(tools)
```

`available_for` returns tools where: model `supports_tools`; plan in `tool.plans` and `plans.limits.tools` includes the name; the required preference is true; the per-turn toggle (composer) did not disable it; the system setting `disabled_tools` doesn't include it; and (for `file_search`) the user has ≥ 1 ready file.

## 4. Schema

JSON Schema generated from the Pydantic parameters model with `model_json_schema()`, post-processed to a strict subset: `type: object`, `properties`, `required`, `additionalProperties: false`, string `maxLength`, numeric bounds, enums. `$defs` are inlined. Descriptions are concise and imperative.

## 5. Permissions

| Check | Where | Failure result |
|---|---|---|
| Tool exists in registry | ToolEngine | `denied`, error `TOOL_NOT_FOUND` (model told "tool not available") |
| Tool available for this user/turn (§3) | ToolEngine | `denied`, `TOOL_NOT_ALLOWED` |
| Quota (`tool_calls` per day per tool) | QuotaService | `denied`, `QUOTA_EXCEEDED` (model told to answer without it) |
| Rate limit (per user per tool per minute) | RateLimiter | `denied`, `RATE_LIMITED` |
| Max calls per turn: 8 total, 3 per tool | ToolEngine | `denied`, `TOOL_LIMIT_REACHED` |
| Resource ownership (file_search file ids) | Tool implementation via repositories | ids dropped |

Denied calls are still persisted and shown ("Web search is turned off in settings").

## 6. Validation

1. Parse `arguments_json` with `json.loads` (max 32 KB) → failure → `failed`, `INVALID_ARGUMENTS`, model content `{"error":"INVALID_ARGUMENTS","detail":"<json error position>"}`.
2. `parameters_model.model_validate(obj)` (strict mode) → failure → same code with Pydantic error summary (field paths + messages, no echo of huge values).
3. Tool-specific semantic validation inside `run` (e.g., code size).

## 7. Execution (`app/tools/engine.py`)

```python
async def execute_all(self, calls: list[LLMToolCall], ctx: ToolContext, iteration: int) -> list[ExecutedTool]:
    results = []
    for call in calls[: MAX_CALLS_PER_ITERATION]:        # 4; sequential in v1 for predictability
        row = await self.repo.insert(tool_call=..., status="pending", iteration=iteration)
        decision = await self.authorize(call, ctx)
        if decision.denied: results.append(await self.finish(row, decision.result)); continue
        args = self.validate(call)                         # may produce failed result
        await self.broker.publish(tool_start(row, label))  # SSE
        await self.repo.mark_running(row)
        try:
            result = await asyncio.wait_for(tool.run(args, ctx), timeout=tool.timeout_seconds)
        except asyncio.TimeoutError:
            result = ToolResult(status="timed_out", error_code="TOOL_TIMEOUT", ...)
        except ToolError as e:
            result = ToolResult(status="failed", error_code=e.code, ...)
        except Exception:
            log.exception("tool.unhandled", tool=call.name)
            result = ToolResult(status="failed", error_code="TOOL_ERROR", model_content='{"error":"TOOL_ERROR"}', ...)
        results.append(await self.finish(row, result))     # persist + parts + SSE tool_result + usage
    return results
```

- Cancellation: `ctx.cancel_event` is passed; tools must check it and abort (code execution sends cancel to sandbox).
- Timeouts: calculator 1 s, file_search 5 s, web_search 20 s, code_execution 30 s (sandbox wall limit 10–20 s + overhead).
- Tool results are fitted into context (`16_CONTEXT_MANAGEMENT.md` §7).
- Untrusted output: every `model_content` is wrapped as `{"tool":"web_search","untrusted_content":true,"data":...}` and the system prompt states tool output is data.

## 8. Persistence and UI

- `tool_calls` row lifecycle: `pending → running → succeeded|failed|timed_out` or `pending → denied`.
- Message parts: `tool_call` part at start, `tool_result` (or `code`) part at finish.
- SSE: `tool_start`, `tool_result` (`13_STREAMING.md`).
- UI `ToolActivity` component: collapsible row with icon, label, spinner/status, duration; expanded view per tool (search results list, calculator expression/result, file matches, code + output).

## 9. Logging and metrics

- Log `tool.call.completed`: tool_name, status, latency_ms, error_code, user_id, message_id (arguments are **not** logged for web_search/code_execution; calculator expression logged at DEBUG only).
- Metrics: `nova_tool_calls_total{tool,status}`, `nova_tool_latency_seconds{tool}`.
- Usage records: `web_search` and `code_execution` create `usage_records(kind=tool name, provider=search|sandbox)`.

## 10. Error model

| Code | Meaning | Model receives |
|---|---|---|
| TOOL_NOT_FOUND | Unknown name | "Tool X is not available." |
| TOOL_NOT_ALLOWED | Disabled by plan/prefs/admin | "Tool X is disabled for this user; answer without it." |
| INVALID_ARGUMENTS | Bad JSON/schema | error detail to self-correct (max 1 correction per tool per turn) |
| TOOL_TIMEOUT | Exceeded timeout | "Tool timed out." |
| TOOL_ERROR | Internal failure | "Tool failed." |
| QUOTA_EXCEEDED / RATE_LIMITED | Limits | "Tool limit reached today." |
| TOOL_LIMIT_REACHED | Per-turn cap | "Tool call limit reached for this answer." |

## 11. Initial tools

### 11.1 `calculator`
- Params: `{"expression": str (≤ 500 chars)}`.
- Implementation: **safe AST evaluator** (`ast.parse(mode="eval")`) allowing only: numeric literals, `+ - * / // % **`, unary ±, parentheses, and whitelisted functions/constants from `math` (`sqrt, log, log10, log2, exp, sin, cos, tan, asin, acos, atan, floor, ceil, factorial (n ≤ 170), pi, e, abs, round, min, max`). `decimal.Decimal` context with 50-digit precision for `+ - * /`. Exponent guard: `|exponent| ≤ 1000` and result magnitude ≤ 1e308. No names, attributes, calls to anything else, comprehensions, or lambdas → `INVALID_ARGUMENTS`.
- Result: `{"expression": "...", "result": "..."}`.
- Plans: all. No quota beyond per-turn limits.

### 11.2 `file_search`
- Params: `{"query": str (1..500), "file_ids": [uuid] (optional, ≤ 20), "top_k": int (1..10, default 6)}`.
- Implementation: `RagService.search(user_id, query, file_ids or whole library, top_k)` with all permission filters (`20_RAG_SYSTEM.md` §6).
- Result: numbered excerpts registered as citations (file sources) so the model can cite `[n]`.
- Plans: all. Quota: shares `rag_search` limit (60/min).

### 11.3 `web_search`
See `23_WEB_SEARCH.md`. Params: `{"query": str (1..300), "recency_days": int|null (1..3650), "max_results": int (1..8, default 5)}`. Plans: all (free: 10/day, plus: 100/day, pro: 500/day).

### 11.4 `code_execution`
See `24_CODE_EXECUTION.md`. Params: `{"language": "python", "code": str (≤ 20,000 chars)}`. Plans: all (free: 10/day, plus: 100/day, pro: 500/day). Requires `code_execution_enabled`.

## 12. Adding a tool (procedure)

1. ADR + update this document (schema, permissions, quotas, security review).
2. Implement `Tool` in `app/tools/<name>.py`; register explicitly.
3. Add plan limits keys, UI renderer for `display`, tests (unit, authorization, timeout, cancellation), and eval cases (`41_AI_EVALUATION.md` tool correctness).
4. Security review for SSRF/injection/data exposure.
