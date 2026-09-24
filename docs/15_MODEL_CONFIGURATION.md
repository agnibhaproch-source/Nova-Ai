# 15 — Model Configuration

## 1. Principles

- The application refers to models by stable **model keys** (`primary`, `fast`, `vision`). Groq model identifiers (`groq_model_id`) are **configuration**, supplied by operators from current Groq documentation. **No Groq model ID is hard-coded anywhere in code, tests (except the stub server fixtures, which use the literal `test-model-*`), or these docs.**
- All model facts (context window, output limit, capabilities, prices) live in one registry file: `apps/api/config/models.yaml`, loaded by `ModelRegistry` (`app/ai/models_registry.py`).
- Values that must come from Groq docs are written as `null` in the committed file; startup validation (§4) fills what it can from Groq's model list and fails loudly for what it cannot.

## 2. Registry file

`apps/api/config/models.yaml` (committed):

```yaml
version: 1

defaults:
  model_key: primary            # used when user/conversation has no model
  purposes:                     # which model_key serves internal purposes
    chat: primary
    title: fast
    summary: fast
    memory_extraction: fast
    query_rewrite: fast
    eval_judge: primary

models:
  - key: primary
    groq_model_id: ${GROQ_DEFAULT_MODEL:-openai/gpt-oss-120b}   # facts below verified from Groq docs
    display_name: "Nova Standard"
    description: "Best quality for most tasks."
    enabled: true
    context_window: null                          # tokens; from Groq docs or models.list
    max_output_tokens: null                       # tokens; from Groq docs (REQUIRED)
    default_max_output_tokens: 2048               # per-response default (≤ max_output_tokens)
    default_temperature: 0.7
    default_top_p: 1.0
    supports_streaming: true
    supports_tools: null                          # REQUIRED true/false from Groq docs
    supports_parallel_tool_calls: false
    supports_json_mode: null                      # REQUIRED true/false
    supports_vision: false
    fallback_key: fast
    plans: [free, plus, pro]
    pricing:                                      # USD per 1M tokens from Groq pricing page; null = unknown
      input_per_million_usd: null
      output_per_million_usd: null

  - key: fast
    groq_model_id: ${GROQ_FAST_MODEL}             # REQUIRED — smaller/faster Groq model
    display_name: "Nova Fast"
    description: "Fastest responses for simple tasks."
    enabled: true
    context_window: null
    max_output_tokens: null
    default_max_output_tokens: 1024
    default_temperature: 0.7
    default_top_p: 1.0
    supports_streaming: true
    supports_tools: null
    supports_parallel_tool_calls: false
    supports_json_mode: null
    supports_vision: false
    fallback_key: null
    plans: [free, plus, pro]
    pricing: { input_per_million_usd: null, output_per_million_usd: null }

  - key: vision
    groq_model_id: ${GROQ_VISION_MODEL:-}         # OPTIONAL — entry auto-disabled when empty
    display_name: "Nova Vision"
    description: "Understands images."
    enabled: true
    context_window: null
    max_output_tokens: null
    default_max_output_tokens: 1024
    default_temperature: 0.5
    default_top_p: 1.0
    supports_streaming: true
    supports_tools: null
    supports_parallel_tool_calls: false
    supports_json_mode: null
    supports_vision: true
    max_images_per_request: null                  # from Groq docs (REQUIRED if enabled)
    max_image_bytes: 4194304
    fallback_key: null
    plans: [plus, pro]
    pricing: { input_per_million_usd: null, output_per_million_usd: null }

audio:
  stt:
    groq_model_id: ${GROQ_STT_MODEL:-}            # OPTIONAL — voice input disabled when empty
    max_audio_seconds: 600
    max_upload_bytes: 26214400
    pricing: { per_hour_usd: null }
  tts:
    groq_model_id: ${GROQ_TTS_MODEL:-}            # OPTIONAL — voice output disabled when empty
    voices: []                                     # list of voice ids from Groq docs, e.g. set via GROQ_TTS_VOICES (comma-separated)
    voices_env: GROQ_TTS_VOICES
    default_voice_env: GROQ_TTS_DEFAULT_VOICE
    max_input_chars: null                          # from Groq docs (REQUIRED if enabled)
    pricing: { per_million_chars_usd: null }
```

Env interpolation syntax: `${VAR}` (required, error if unset/empty), `${VAR:-default}` (optional). Implemented by `ModelRegistry` before YAML parsing (`os.path.expandvars` is **not** used because it silently leaves unknown vars).

An operator may override the file path with `MODEL_REGISTRY_PATH` (e.g., a mounted config in production).

## 3. Pydantic schema

```python
class Pricing(BaseModel):
    input_per_million_usd: Decimal | None = None
    output_per_million_usd: Decimal | None = None

class ModelConfig(BaseModel):
    key: constr(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    groq_model_id: str
    display_name: str
    description: str = ""
    enabled: bool = True
    context_window: PositiveInt | None
    max_output_tokens: PositiveInt | None
    default_max_output_tokens: PositiveInt
    default_temperature: confloat(ge=0, le=2)
    default_top_p: confloat(gt=0, le=1)
    supports_streaming: bool = True
    supports_tools: bool | None
    supports_parallel_tool_calls: bool = False
    supports_json_mode: bool | None
    supports_vision: bool = False
    max_images_per_request: PositiveInt | None = None
    max_image_bytes: PositiveInt = 4 * 1024 * 1024
    image_token_cost: PositiveInt = 1500              # context estimator cost per image (16 §2)
    token_estimate_bytes_per_token: confloat(gt=1, le=8) = 3.2   # estimator calibration (16 §2)
    fallback_key: str | None = None
    plans: list[Literal["free","plus","pro"]]
    pricing: Pricing = Pricing()
    deprecation_date: date | None = None
```

## 4. Startup validation (`ModelRegistry.load()` + `GroqService.verify_models()`)

1. Parse and interpolate. Entries whose `groq_model_id` resolves to empty are set `enabled=false` with a WARN log.
2. `defaults.model_key` and every `defaults.purposes.*` must reference enabled models → else **fatal** (process exits non-zero).
3. `fallback_key` must reference an enabled model with the same or broader capabilities (no cycles).
4. In `staging`/`production` (and in `development` when `GROQ_API_KEY` is set): call `models.list()`:
   - Missing `groq_model_id` → fatal for `primary`/`fast`; optional models disabled with ERROR log.
   - If `context_window` is `null` and Groq reports a context window → adopt it; log INFO `model_registry.adopted`.
5. After step 4, any enabled model with `context_window`, `max_output_tokens`, `supports_tools`, or `supports_json_mode` still `null` → **fatal** with a message naming the field and "set it from Groq documentation in config/models.yaml". (`max_output_tokens` and capability flags are never guessed.)
6. `default_max_output_tokens ≤ max_output_tokens` and `max_output_tokens < context_window`.
7. Pricing `null` is allowed; cost estimates are then `NULL` and the admin dashboard shows "cost unknown" with a warning badge.

In `development`, a failed validation is logged as `startup.config_invalid` and the API keeps serving non-chat features; chat endpoints return `MODEL_NOT_AVAILABLE` with an explanatory message until the registry is fixed. In `staging`/`production` it is fatal.

In `APP_ENV=test`, the stub server provides a models list and the test registry file `tests/fixtures/models.test.yaml` supplies all values.

## 5. Runtime access

```python
registry.resolve(model_key) -> ModelConfig              # enabled only; raises ModelNotAvailableError
registry.for_purpose("title") -> ModelConfig
registry.list_for_plan(plan_key) -> list[ModelConfig]
registry.audio_stt() -> SttConfig | None
registry.audio_tts() -> TtsConfig | None
```

The registry is immutable per process. Admin toggles (`/admin/models`) write `system_settings.disabled_model_keys` (list); `ModelRegistry.is_enabled()` consults that setting (cached 30 s) so admins can disable a model without redeploying. Changing Groq IDs or capabilities requires a config change + deploy.

## 6. User-facing model selection

- `GET /api/v1/models` returns models enabled **and** allowed for the principal's plan:
  ```json
  {"data":[{"key":"primary","display_name":"Nova Standard","description":"...","capabilities":{"tools":true,"vision":false,"json":true},"context_window":131072,"is_default":true}]}
  ```
  (numbers shown are whatever the registry holds; the example value is illustrative only). Groq model IDs are **not** exposed to end users; admins see them.
- Composer model picker lists these; models not in the user's plan appear disabled with "Plus"/"Pro" badge linking to billing.
- If a conversation's `model_key` becomes unavailable, the next send uses the default model and the UI shows a one-time notice.

## 7. Generation parameters policy

| Parameter | Source | User-adjustable? |
|---|---|---|
| temperature | model default; purposes override (title 0.3, summary 0.2, memory extraction 0.0, query rewrite 0.0, judge 0.0) | No (v1) |
| top_p | model default | No |
| max_output_tokens | `default_max_output_tokens`, clamped by remaining context budget and by plan `max_output_tokens` limit | No |
| seed | set only for evals (`seed=7`) | No |
| tools | per user preferences/plan/model capability | Via toggles |

## 8. Changing models (operational procedure)

1. Read Groq documentation for the new model: ID, context window, max output, tool/JSON/vision support, pricing, deprecation dates.
2. Update the env var (`GROQ_DEFAULT_MODEL` etc.) and `models.yaml` values in a PR.
3. Run the eval suites (`41_AI_EVALUATION.md`) against the new model in staging; compare with the baseline report.
4. Deploy; watch `nova_groq_errors_total` and TTFT dashboards for 24 h.
5. When Groq announces deprecation of a configured model, an admin banner appears if `deprecation_date` is added to the registry entry (optional field `deprecation_date: YYYY-MM-DD`; admin dashboard warns 30 days before).
