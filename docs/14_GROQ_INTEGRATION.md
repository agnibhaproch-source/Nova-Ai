# 14 — Groq Integration

> Groq is the **only** LLM provider (`00_MASTER_INSTRUCTION.md` R1). This document is the contract for every model call in the system. Before implementing, verify every SDK attribute/parameter named here against the pinned version of the official `groq` Python SDK and current Groq API documentation; where this document says "verify", the implementer must confirm the exact field name and adjust the adapter (not the rest of the system).

## 1. Layering

```
ChatService / TitleService / SummaryService / MemoryService / VoiceService / evals
                │   (depend only on GroqService's typed methods)
                ▼
        GroqService  (app/ai/groq/service.py)
          • model resolution via ModelRegistry
          • retries, fallback model, timeouts
          • metrics, tracing, logging, usage extraction
                │   (depends on LLMProvider protocol)
                ▼
        GroqProvider (app/ai/groq/provider.py)  implements LLMProvider
          • converts internal types ↔ Groq wire format (converters.py)
          • calls AsyncGroq (client.py)
          • maps SDK exceptions → ProviderError (errors.py)
                │
                ▼
        AsyncGroq (official SDK)  ──HTTPS──► Groq API
```

Only modules under `app/ai/groq/` may `import groq` (Ruff `banned-api` rule). Nothing outside `app/ai/` knows Groq's wire format.

## 2. Client initialization and authentication

`app/ai/groq/client.py`:

```python
from groq import AsyncGroq
import httpx

_client: AsyncGroq | None = None

def get_groq_client(settings: Settings) -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(
            api_key=settings.GROQ_API_KEY.get_secret_value(),   # SecretStr
            base_url=settings.GROQ_BASE_URL or None,             # None → SDK default; override allowed only when APP_ENV == "test"
            max_retries=0,                                       # retries owned by GroqService
            timeout=httpx.Timeout(connect=5.0, read=settings.GROQ_TIMEOUT_SECONDS, write=10.0, pool=5.0),
            http_client=httpx.AsyncClient(
                limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
                timeout=None,  # SDK timeout used
            ),
        )
    return _client
```

- One client per process, created in FastAPI `lifespan` and ARQ `on_startup`; closed on shutdown (`await client.close()`).
- `GROQ_API_KEY` is a `SecretStr`; startup fails in non-test envs if empty. It is never logged (redaction processor, `38_LOGGING.md` §5).
- `Settings` validation refuses `GROQ_BASE_URL` when `APP_ENV in {"staging","production"}`.

## 2a. User-supplied keys (BYOK, default)

`GROQ_KEY_MODE=user` (default): every conversation runs on a Groq API key its owner supplies when starting the chat. The default model is `openai/gpt-oss-120b`.

- **Entry:** `POST /conversations {groq_api_key}` (required in this mode, else `428 GROQ_KEY_REQUIRED`). Re-entry: `PUT /conversations/{id}/groq-key {api_key}`. Status: `GET /conversations/{id}/groq-key` → `{mode, configured, expires_in_seconds}` (never the key). Removal: `DELETE /conversations/{id}/groq-key`.
- **Validation:** the key must look like `gsk_…` and pass an authenticated `GET /openai/v1/models` call; Groq `401/403` → `422 GROQ_KEY_INVALID`. Rejected keys are never stored.
- **Storage:** AES-GCM encrypted (key derived from `AUTH_SECRET`, conversation id as associated data) in Redis at `nova:{env}:groqkey:{conversation_id}` with a sliding TTL (`GROQ_USER_KEY_TTL_HOURS`, default 720 = 30 days). Never in Postgres, logs, analytics or responses. When it expires the UI asks for the key again.
- **Use:** `app/ai/groq/keys.py` holds the key in a `ContextVar`; `get_groq_client()` returns a per-key `AsyncGroq` (LRU, shared httpx pool). The generation runner sets it for its task; title, summary and memory jobs load the conversation's key and are skipped if it has expired.
- **Circuit breaker:** per-key failures (`GROQ_KEY_INVALID`, `PROVIDER_RATE_LIMITED`) are not counted toward the shared per-model circuit.
- **Voice:** STT and Groq TTS need `GROQ_KEY_MODE=server` (they aren't tied to a conversation); in BYOK mode voice input is off and read-aloud uses the browser's speech synthesis.
- The browser still never calls Groq: the key goes browser → BFF → API once, over the same authenticated, CSRF-protected path as any other request.

`GROQ_KEY_MODE=server` restores the single server-held `GROQ_API_KEY` for everyone (required in staging/prod only in this mode).

## 3. Internal types (`app/ai/provider.py`)

```python
Role = Literal["system", "user", "assistant", "tool"]

@dataclass(frozen=True)
class ImageInput:            # only for vision-capable models
    data_url: str | None     # "data:image/png;base64,..." (≤ 4 MB after re-encode)
    url: str | None          # presigned S3 GET URL alternative (verify Groq support; default: data_url)

@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str | None = None
    images: tuple[ImageInput, ...] = ()
    tool_calls: tuple["LLMToolCall", ...] = ()   # assistant only
    tool_call_id: str | None = None               # tool only
    name: str | None = None                       # tool name for tool messages

@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments_json: str

@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict           # JSON Schema (draft 2020-12 subset)

@dataclass(frozen=True)
class ChatRequest:
    model_key: str
    messages: Sequence[LLMMessage]
    temperature: float | None = None
    top_p: float | None = None
    max_output_tokens: int | None = None
    tools: Sequence[ToolSchema] = ()
    tool_choice: Literal["auto", "none", "required"] = "auto"
    json_mode: bool = False
    stop: Sequence[str] = ()
    seed: int | None = None
    purpose: Literal["chat","title","summary","memory_extraction","eval","query_rewrite"] = "chat"
    end_user_hash: str | None = None

@dataclass
class ChatChunk:                       # streaming unit
    text_delta: str = ""
    tool_call_deltas: list["ToolCallDelta"] = field(default_factory=list)
    finish_reason: str | None = None   # "stop" | "length" | "tool_calls" | "content_filter" | None
    usage: "Usage | None" = None       # present on the final chunk when Groq reports it

@dataclass
class ToolCallDelta:
    index: int
    id: str | None
    name: str | None
    arguments_fragment: str

@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    queue_time_ms: int | None = None
    provider_total_time_ms: int | None = None

@dataclass(frozen=True)
class ChatResult:
    text: str
    tool_calls: tuple[LLMToolCall, ...]
    finish_reason: str
    usage: Usage | None
    groq_model_id: str
    latency_ms: int

class LLMProvider(Protocol):
    def stream_chat(self, req: ResolvedChatRequest) -> AsyncIterator[ChatChunk]: ...
    async def complete(self, req: ResolvedChatRequest) -> ChatResult: ...
    async def transcribe(self, audio: bytes, filename: str, model_id: str, language: str | None) -> TranscriptionResult: ...
    async def synthesize(self, text: str, model_id: str, voice: str, fmt: str) -> AsyncIterator[bytes]: ...
    async def list_models(self) -> list[ProviderModelInfo]: ...
```

`ResolvedChatRequest` = `ChatRequest` + `groq_model_id` + resolved defaults (produced by `GroqService` from `ModelRegistry`).

## 4. `GroqService` public API

```python
class GroqService:
    async def stream_chat(self, req: ChatRequest, *, ctx: CallContext) -> AsyncIterator[ChatChunk]
    async def complete(self, req: ChatRequest, *, ctx: CallContext) -> ChatResult
    async def complete_json(self, req: ChatRequest, schema: type[BaseModel], *, ctx: CallContext) -> BaseModel
    async def transcribe(self, audio: bytes, filename: str, *, language: str | None, ctx: CallContext) -> TranscriptionResult
    def synthesize(self, text: str, *, voice: str, fmt: Literal["mp3","wav"], ctx: CallContext) -> AsyncIterator[bytes]
    async def verify_models(self) -> ModelVerificationReport     # startup + admin "Models" page

@dataclass(frozen=True)
class CallContext:
    request_id: str
    user_id: UUID | None
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    api_key_id: UUID | None = None
    cancel_event: asyncio.Event | None = None
```

`CallContext` drives tracing attributes, logging fields, and the `usage_records` row that `GroqService` returns in the result (`UsageDraft`) for the caller to persist in its transaction (GroqService does not touch the DB).

## 5. Request construction

### 5.1 Model resolution
`ModelRegistry.resolve(model_key)` → `ModelConfig` (`15_MODEL_CONFIGURATION.md`). Unknown/disabled key → `ModelNotAvailableError` (`422 MODEL_NOT_AVAILABLE`). Defaults from the model config fill `temperature`, `top_p`, `max_output_tokens` when the request leaves them `None`. `max_output_tokens` is clamped to `model.max_output_tokens`.

### 5.2 Message conversion (`converters.py`)

| Internal | Groq wire (OpenAI-compatible chat schema) |
|---|---|
| `LLMMessage(role="system", content)` | `{"role":"system","content": content}` |
| `LLMMessage(role="user", content, images=())` | `{"role":"user","content": content}` |
| `LLMMessage(role="user", content, images=[...])` | `{"role":"user","content":[{"type":"text","text":content}, {"type":"image_url","image_url":{"url": data_url}} ...]}` — only if model `supports_vision`; otherwise converter raises `CapabilityError` |
| `LLMMessage(role="assistant", content, tool_calls=[...])` | `{"role":"assistant","content": content or None, "tool_calls":[{"id","type":"function","function":{"name","arguments"}}]}` |
| `LLMMessage(role="tool", tool_call_id, name, content)` | `{"role":"tool","tool_call_id": id, "name": name, "content": content}` (verify whether `name` is accepted; omit if rejected) |
| `ToolSchema` | `{"type":"function","function":{"name","description","parameters"}}` |

Consecutive messages of the same role are allowed; empty assistant content with no tool calls is dropped.

### 5.3 Parameters sent

```python
params = dict(
    model=groq_model_id,
    messages=wire_messages,
    stream=stream,
    temperature=req.temperature,
    top_p=req.top_p,
    max_completion_tokens=max_output_tokens,   # verify name; fall back to "max_tokens" if the SDK version requires
    stop=list(req.stop) or None,
    seed=req.seed,
    user=req.end_user_hash,                    # HMAC_SHA256(AUTH_SECRET, "groq-user:" + user_id)[:32] — opaque (PRV-008)
)
if req.tools and model.supports_tools and req.tool_choice != "none":
    params["tools"] = wire_tools
    params["tool_choice"] = req.tool_choice
    params["parallel_tool_calls"] = model.supports_parallel_tool_calls   # verify support per model
if req.json_mode:
    params["response_format"] = {"type": "json_object"}                 # requires model.supports_json_mode
params = {k: v for k, v in params.items() if v is not None}
```

For streaming, request usage in the final chunk if the SDK/API supports `stream_options={"include_usage": True}` (verify); otherwise read Groq's final-chunk usage extension (see §7).

## 6. Streaming

```python
async def stream_chat(self, req, ctx):
    model = self.registry.resolve(req.model_key)
    attempt = 0
    while True:
        started = monotonic(); first_token_at = None; emitted_any = False
        try:
            async with self._concurrency.acquire(model):                 # per-model semaphore (§11)
                stream = await self.provider.open_stream(resolved(req, model))
                async with stream:                                        # guarantees HTTP close
                    async for chunk in with_idle_timeout(stream, 30.0):  # PROVIDER_TIMEOUT if idle 30s
                        if ctx.cancel_event and ctx.cancel_event.is_set():
                            raise GenerationCancelled()
                        if chunk.text_delta or chunk.tool_call_deltas:
                            if first_token_at is None: first_token_at = monotonic()
                            emitted_any = True
                        yield chunk
            return
        except RetryableProviderError as e:
            if emitted_any or attempt >= settings.GROQ_MAX_RETRIES:
                raise
            attempt += 1
            await asyncio.sleep(backoff(attempt, e.retry_after))
        except ModelUnavailableError:
            if model.fallback_key and not emitted_any:
                model = self.registry.resolve(model.fallback_key); continue
            raise
```

Provider chunk parsing (`GroqProvider.open_stream`): for each SDK chunk:
- `choice = chunk.choices[0]` if `chunk.choices` else `None`.
- `text_delta = choice.delta.content or ""`.
- `choice.delta.tool_calls` → `ToolCallDelta(index=tc.index, id=tc.id, name=tc.function.name, arguments_fragment=tc.function.arguments or "")`.
- `finish_reason = choice.finish_reason`.
- Usage: see §7.

Tool call accumulation (in `StreamProcessor`, not in the provider): dict keyed by `index`; set `id`/`name` when first non-null; concatenate `arguments_fragment`. At `finish_reason == "tool_calls"` parse each accumulated arguments string with `json.loads`; invalid JSON → the tool call is answered with a `tool` message `{"error":"INVALID_ARGUMENTS", ...}` so the model can self-correct (counts as an iteration).

## 7. Usage extraction

Order of precedence (implement all, verify which the pinned SDK exposes):
1. `chunk.usage` (standard field when present on the final chunk / non-streaming response).
2. `chunk.x_groq.usage` (Groq-specific extension on the final streamed chunk).
3. If neither is present (e.g., cancelled stream): estimate with `TokenEstimator` (prompt tokens estimated at build time by `ContextService`; completion tokens estimated from generated text) and set `usage_records.metadata.estimated = true` — the `usage` SSE event still reports numbers.

Additional timing fields (`queue_time`, `total_time` if reported) are captured into `Usage.queue_time_ms` / `provider_total_time_ms`.

For a turn with tool iterations, usage is **summed** across all Groq calls of the turn and stored on the assistant message; one `usage_records` row is written per Groq call (kind `chat`), all sharing `message_id`.

## 8. Tool calling loop (owned by `GenerationRunner`, uses GroqService)

```
iteration = 0
messages = context.messages
loop:
   stream = groq.stream_chat(ChatRequest(..., tools=tool_schemas, tool_choice="auto" if iteration < MAX else "none"))
   relay text deltas; accumulate tool calls
   if finish_reason != "tool_calls": break
   append assistant LLMMessage(content=text_so_far_this_iteration, tool_calls=calls)
   results = await tool_engine.execute_all(calls, ctx)         # 22_TOOL_SYSTEM.md
   append LLMMessage(role="tool", tool_call_id=..., name=..., content=result.model_content) for each
   iteration += 1
   if iteration > MAX_TOOL_ITERATIONS (5): next call uses tool_choice="none"
```

- Tools are passed only if the model config has `supports_tools: true` and at least one tool is enabled for the user.
- `ContextService.fit_tool_results()` re-checks the token budget before each follow-up call; oversize tool content is truncated with a marker (`16_CONTEXT_MANAGEMENT.md` §7).

## 9. Non-streaming and JSON calls

- `complete()` uses `stream=False`; same retry/fallback logic (retries allowed since nothing was emitted).
- `complete_json(req, schema)`: sets `json_mode=True` if `supports_json_mode`, else appends instruction "Respond with a single JSON object only." Parses with `schema.model_validate_json`; on failure retries once with the validation error appended; then raises `ProviderResponseInvalid` (`PROVIDER_ERROR`).
- Used by: memory extraction, RAG query rewriting, evaluation judges.

## 10. Errors and mapping (`errors.py`)

| SDK exception / condition | Internal error | Retryable (before first token) | API error code / HTTP |
|---|---|---|---|
| `groq.APIConnectionError` | `ProviderConnectionError` | yes | `PROVIDER_UNAVAILABLE` / 502 |
| `groq.APITimeoutError`, idle timeout | `ProviderTimeoutError` | yes | `PROVIDER_TIMEOUT` / 504 |
| `groq.RateLimitError` (429) | `ProviderRateLimitedError(retry_after)` | yes (honor `retry-after`, max 10 s wait) | `PROVIDER_RATE_LIMITED` / 503 |
| `groq.InternalServerError` / status ≥ 500 (incl. 503) | `ProviderUnavailableError` | yes | `PROVIDER_UNAVAILABLE` / 502 |
| `groq.AuthenticationError` (401), `PermissionDeniedError` (403) | `ProviderAuthError` | no; **page on-call** | `PROVIDER_ERROR` / 502 |
| `groq.NotFoundError` (404) for model | `ModelUnavailableError` | fallback model once | `PROVIDER_MODEL_UNAVAILABLE` / 503 |
| `groq.BadRequestError` (400) with context-length message | `ContextTooLargeError` | no (ContextService re-budgets once with 20% smaller budget, then fails) | `CONTEXT_TOO_LARGE` / 422 |
| `groq.BadRequestError` other / `UnprocessableEntityError` | `ProviderBadRequestError` | no | `PROVIDER_ERROR` / 502 (logged with sanitized params, no content) |
| Any other `groq.APIStatusError` | `ProviderError` | no | `PROVIDER_ERROR` / 502 |

Errors after the first emitted token are **not** retried: the partial message is persisted, status `failed`, SSE `error` event with `retryable: true` (user can Retry = regenerate).

User-facing messages never include provider raw messages (they may echo content); raw provider error bodies are logged at WARN with content fields removed.

## 11. Timeouts, retries, concurrency, rate limits

- Timeouts: connect 5 s; read `GROQ_TIMEOUT_SECONDS` (default 60 s) for non-stream; stream idle 30 s; overall generation 300 s (runner).
- Retries: `GROQ_MAX_RETRIES` (default 2), exponential backoff with full jitter: `sleep = random.uniform(0, min(8, 0.5 * 2**attempt))`, or `retry-after` header value (≤ 10 s) when provided.
- Per-process concurrency: `asyncio.Semaphore(GROQ_MAX_CONCURRENCY_PER_PROCESS)` (default 64) to avoid connection storms.
- **Groq account rate limits:** GroqProvider reads response headers (`x-ratelimit-remaining-requests`, `x-ratelimit-remaining-tokens`, `x-ratelimit-reset-*`, `retry-after`; verify header names) via the SDK's raw response access (`with_raw_response`/`with_streaming_response`, verify API) and stores them in Redis `nova:{env}:groq:ratelimit:{groq_model_id}` (TTL 60 s). When remaining tokens < 5% of limit, `GroqService` proactively applies a short global backoff (throttle new requests for that model by queuing up to 2 s) and emits metric `nova_groq_ratelimit_near_total`. Hitting 429s increments `nova_groq_errors_total{type="rate_limited"}` and alerts when > 1% of requests over 5 min (`39_MONITORING.md`).
- Circuit breaker (per `groq_model_id`, Redis-backed counters): if ≥ 50% of calls fail with retryable errors over the last 60 s with ≥ 20 calls, open the circuit for 30 s: new requests immediately use the fallback model if configured, else fail fast with `PROVIDER_UNAVAILABLE`.

## 12. Logging and tracing

- OTel span `groq.chat` (child of `chat.generate`) attributes: `gen_ai.system="groq"`, `gen_ai.request.model`, `gen_ai.request.max_tokens`, `gen_ai.request.temperature`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons`, `nova.purpose`, `nova.model_key`, `nova.attempt`, `nova.ttft_ms`. **No** prompt or completion content in spans.
- Log event `groq.request.completed` (INFO): request_id, user_id, conversation_id, message_id, model_key, groq_model_id, purpose, attempt, status, latency_ms, ttft_ms, prompt_tokens, completion_tokens, finish_reason, tool_call_count.
- Log event `groq.request.failed` (WARN/ERROR): same + error_type, http_status, retryable.
- Metrics (`39_MONITORING.md`): `nova_groq_requests_total{model_key,purpose,status}`, `nova_groq_latency_seconds` histogram, `nova_groq_ttft_seconds` histogram, `nova_groq_tokens_total{direction}`, `nova_groq_errors_total{type}`.

## 13. Audio (STT/TTS) via Groq

- `transcribe`: `client.audio.transcriptions.create(file=(filename, audio_bytes), model=GROQ_STT_MODEL, language=?, response_format="json")` (verify params). Max upload per Groq limits (verify) — NOVA caps at 25 MB and 10 minutes of audio.
- `synthesize`: `client.audio.speech.create(model=GROQ_TTS_MODEL, voice=voice, input=text, response_format=fmt)` streamed via the SDK's streaming response helper (verify). Text chunked to ≤ the model's input limit (configured `tts_max_input_chars`).
- Both are optional capabilities: enabled only if `GROQ_STT_MODEL` / `GROQ_TTS_MODEL` are set (`26_VOICE_SYSTEM.md`).

## 14. Model listing and verification

`verify_models()` calls `client.models.list()` and checks that every enabled `groq_model_id` exists and is active. Result cached in Redis 10 min and exposed in `/admin/models` and `/readyz` detail (`readyz` does **not** fail on Groq issues; it reports `groq: degraded`). If the list response includes `context_window` (verify field) and the registry value is `null`, the registry adopts it (`15_MODEL_CONFIGURATION.md` §4).

## 15. Provider abstraction policy

- `LLMProvider` exists for clean boundaries and testing. The only production implementation is `GroqProvider`.
- Tests use `tests/fakes/groq_stub_server.py` (an HTTP server emulating the subset of Groq's OpenAI-compatible endpoints used, driven by scripted fixtures) through `GROQ_BASE_URL` in `APP_ENV=test`, or an `httpx.MockTransport` injected into `AsyncGroq(http_client=...)` for unit tests.
- Adding any non-Groq `LLMProvider` implementation is prohibited without changing `00_MASTER_INSTRUCTION.md` R1 by the product owner.

## 16. Testing checklist

- Converter unit tests for every message shape and tool schema.
- Streaming parser: text only; tool calls across many fragments; multiple parallel tool calls; usage on final chunk (`usage` and `x_groq.usage` variants); missing usage.
- Retry: 429 with retry-after before first token → retried; error after first token → not retried.
- Fallback: 404 model → fallback used, metric incremented.
- Cancellation closes the upstream HTTP stream (assert stub server sees disconnect).
- Secrets: log capture contains no API key; exception messages sanitized.
- Nightly live smoke test (`46_CI_CD.md` §6) against real Groq with `GROQ_API_KEY` from GitHub Environment `nightly`.
