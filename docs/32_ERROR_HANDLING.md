# 32 — Error Handling

## 1. Principles

1. Every error returned to a client uses the standard envelope and a stable, documented `code`.
2. Messages are safe for end users: no stack traces, SQL, internal hostnames, file paths, provider raw messages, secrets, or other users' data.
3. Every error response carries `request_id`; logs and Sentry events carry the same id for correlation.
4. Expected errors (validation, not found, limits) are logged at INFO/WARN without stack traces; unexpected errors at ERROR with stack traces (server-side only) and reported to Sentry.
5. Fail closed on security checks; fail gracefully on optional dependencies.

## 2. Envelope

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "You're sending messages too quickly. Try again in 20 seconds.",
    "details": [],
    "request_id": "01J…",
    "retryable": true,
    "retry_after_seconds": 20
  }
}
```

- `details`: for `VALIDATION_ERROR`, `[{ "field": "body.title", "issue": "string_too_long", "message": "Must be at most 200 characters." }]`; for others usually empty.
- `retry_after_seconds` only when meaningful; mirrors the `Retry-After` header.

In SSE, errors use the `error` event with the same fields (`13_STREAMING.md` §3).

## 3. Backend implementation

```python
class ErrorCode(StrEnum): ...        # app/core/errors.py — all codes below

class AppError(Exception):
    code: ErrorCode
    http_status: int
    message: str                     # safe default message per code
    details: list[dict] = []
    retryable: bool = False
    retry_after: int | None = None

class NotFoundError(AppError): code = ErrorCode.RESOURCE_NOT_FOUND; http_status = 404
class ConflictError(AppError): ...
class QuotaExceededError(AppError): ...
class ProviderError(AppError): ...
# etc.
```

Exception handlers registered in `create_app()`:

| Exception | Handling |
|---|---|
| `AppError` | Envelope with its code/status; log level by status (4xx INFO/WARN, 5xx ERROR) |
| `RequestValidationError` (FastAPI) | `422 VALIDATION_ERROR` with mapped details (input values are **not** echoed) |
| `StarletteHTTPException` 404/405 | `404 RESOURCE_NOT_FOUND` / `405 METHOD_NOT_ALLOWED` |
| `sqlalchemy.exc.IntegrityError` | Mapped by constraint name via `CONSTRAINT_ERROR_MAP` (e.g., `uq_users_email_active` → `EMAIL_ALREADY_REGISTERED`); unmapped → `409 CONFLICT` + ERROR log |
| `sqlalchemy.exc.OperationalError`, `DBAPIError` (connection) | `503 DATABASE_ERROR`, retryable |
| `redis.exceptions.ConnectionError` | Handled locally where degraded mode exists; otherwise `503 SERVICE_DEGRADED` |
| `botocore`/aioboto3 errors | `503 STORAGE_ERROR` (retryable) |
| `asyncio.TimeoutError` (request-level) | `504 TIMEOUT` |
| `Exception` (catch-all) | `500 INTERNAL_ERROR`, Sentry capture, ERROR log with stack |

A `ServerErrorMiddleware`-level guard ensures that even errors in middleware return the JSON envelope.

## 4. Error code catalogue

### 4.1 Auth & access
| Code | HTTP | Retryable | Default message |
|---|---|---|---|
| AUTH_REQUIRED | 401 | no | Please log in to continue. |
| AUTH_INVALID | 401 | no | Your credentials are invalid. |
| INVALID_CREDENTIALS | 401 | no | Incorrect email or password. |
| ACCOUNT_LOCKED | 423 | yes (after) | Too many attempts. Try again later. |
| ACCOUNT_SUSPENDED | 403 | no | This account has been suspended. Contact support. |
| FORBIDDEN | 403 | no | You don't have permission to do that. |
| CSRF_FAILED | 403 | no | Your session needs to be refreshed. Reload the page. |
| INSUFFICIENT_SCOPE | 403 | no | This API key doesn't have permission for this action. |
| SIGNUPS_DISABLED | 403 | no | Sign-ups are temporarily closed. |
| PLAN_FEATURE_UNAVAILABLE | 403 | no | This feature isn't included in your plan. |
| TOKEN_INVALID | 400 | no | This link is invalid or has expired. |

### 4.2 Validation & request
| Code | HTTP | Message |
|---|---|---|
| VALIDATION_ERROR | 422 | Some fields are invalid. |
| PASSWORD_POLICY | 422 | Choose a stronger password (at least 12 characters, not a common password). |
| CONFIRMATION_REQUIRED | 422 | Please confirm this action. |
| REASON_REQUIRED | 422 | A reason is required for this action. |
| INVALID_CURSOR | 400 | Invalid pagination cursor. |
| PAYLOAD_TOO_LARGE | 413 | The request is too large. |
| METHOD_NOT_ALLOWED | 405 | Method not allowed. |
| IDEMPOTENCY_KEY_REUSED | 409 | This request key was already used with different data. |

### 4.3 Resources & state
| Code | HTTP | Message |
|---|---|---|
| RESOURCE_NOT_FOUND | 404 | Not found. |
| CONFLICT | 409 | This change conflicts with the current state. Refresh and try again. |
| EMAIL_ALREADY_REGISTERED | 409 | An account with this email already exists. |
| LIMIT_REACHED | 409 | You've reached the limit for this item. |
| GENERATION_IN_PROGRESS | 409 | Wait for the current response to finish or stop it. |
| CONVERSATION_DELETED | 409 | This conversation is in the trash. Restore it to continue. |
| NOT_IN_TRASH | 409 | Only conversations in the trash can be deleted permanently. |
| INVALID_MESSAGE_STATE | 409 | This message can't be changed right now. |
| INVALID_FILE_STATE | 409 | This file can't be processed in its current state. |
| FILE_NOT_READY | 409 | This file is still processing. |
| CANNOT_MODIFY_SELF | 409 | You can't change your own role or status. |
| EXPORT_NOT_READY | 409 | Your export is still being prepared. |
| EXPORT_EXPIRED | 410 | This export has expired. Request a new one. |
| RESTORE_WINDOW_EXPIRED | 410 | This item can no longer be restored. |

### 4.4 Files & media
| Code | HTTP | Message |
|---|---|---|
| UNSUPPORTED_FILE_TYPE | 415 | This file type isn't supported. |
| FILE_TYPE_MISMATCH | 415 | The file's contents don't match its type. |
| FILE_TOO_LARGE | 413 | This file is larger than your plan allows. |
| STORAGE_QUOTA_EXCEEDED | 413 | You've used all your file storage. Delete some files to free up space. |
| UPLOAD_INVALID | 422 | The upload didn't complete correctly. Try again. |
| INVALID_FILE | 422 | This file can't be used here. |
| AUDIO_TOO_LONG | 413 | Recording is too long (max 10 minutes). |
| NO_SPEECH_DETECTED | 422 | We couldn't hear any speech. Try again. |
| MEMORY_CONTENT_REJECTED | 422 | This can't be saved as a memory (it may contain sensitive data). |

File processing codes stored on `files.error_code` (not HTTP): `EXTRACTION_FAILED`, `NO_EXTRACTABLE_TEXT`, `FILE_ENCRYPTED`, `FILE_TOO_COMPLEX`, `FILE_MALWARE_DETECTED`, `SCAN_UNAVAILABLE`, `EMBEDDING_UNAVAILABLE`, `EMBEDDING_DIMENSION_MISMATCH`, `FILE_TYPE_MISMATCH`.

### 4.5 AI / models
| Code | HTTP | Retryable | Message |
|---|---|---|---|
| MODEL_NOT_AVAILABLE | 422 | no | This model isn't available. Choose another model. |
| MODEL_CAPABILITY_MISSING | 422 | no | The selected model can't handle this input (e.g., images). |
| CONTEXT_TOO_LARGE | 422 | no | Your message is too long for this model. Shorten it or attach it as a file. |
| PROVIDER_ERROR | 502 | yes | The AI provider returned an error. Please try again. |
| PROVIDER_UNAVAILABLE | 502 | yes | Nova's AI provider is having trouble. Try again shortly. |
| PROVIDER_TIMEOUT | 504 | yes | The AI provider took too long to respond. |
| PROVIDER_RATE_LIMITED | 503 | yes | Your Groq API key has hit its rate limit. Try again in a moment. |
| PROVIDER_MODEL_UNAVAILABLE | 503 | yes | This model is temporarily unavailable. |
| GENERATION_INTERRUPTED | — (SSE/status) | yes | The response was interrupted. Retry to generate it again. |
| VOICE_UNAVAILABLE | 503 | no | Voice isn't available right now. |

### 4.6 Tools (SSE `tool_result` / tool_calls.error_code; not HTTP)
`TOOL_NOT_FOUND`, `TOOL_NOT_ALLOWED`, `INVALID_ARGUMENTS`, `TOOL_TIMEOUT`, `TOOL_ERROR`, `TOOL_LIMIT_REACHED`, `SEARCH_UNAVAILABLE`, `SEARCH_RATE_LIMITED`, `SANDBOX_BUSY`. A generic HTTP `TOOL_ERROR` (502) exists only for direct tool-backed endpoints.

### 4.7 Limits
| Code | HTTP | Message |
|---|---|---|
| RATE_LIMITED | 429 | You're doing that too often. Try again in N seconds. |
| EXPORT_RATE_LIMITED | 429 | You can request one export per day. |

Nova has no usage quotas (ADR 0004); the Groq key's own limits surface as `PROVIDER_RATE_LIMITED`.

### 4.8 Billing
Removed with billing (ADR 0004).

### 4.9 Infrastructure
| Code | HTTP | Retryable | Message |
|---|---|---|---|
| DATABASE_ERROR | 503 | yes | Something went wrong on our side. Please try again. |
| STORAGE_ERROR | 503 | yes | File storage is temporarily unavailable. |
| SERVICE_DEGRADED | 503 | yes | This feature is temporarily unavailable. |
| TIMEOUT | 504 | yes | The request took too long. |
| INTERNAL_ERROR | 500 | yes | Something went wrong. Please try again. |

## 5. Frontend handling

- `ApiError` constructed from envelope; unknown codes fall back to `INTERNAL_ERROR` copy.
- Mapping of codes to UI behavior:
  - `AUTH_REQUIRED` → redirect to login (preserve `next`).
  - `CSRF_FAILED` → refetch `/auth/session` (re-issues cookie) and retry the request once automatically.
  - `RATE_LIMITED`/`PROVIDER_RATE_LIMITED` → inline alert with countdown.
  - `VALIDATION_ERROR` → field errors.
  - `retryable` 5xx on idempotent GETs → TanStack retry (2 attempts, backoff); on mutations → toast with "Try again".
  - Provider errors in stream → failed message UI with Retry.
- Request id shown in error details ("Reference: 01J…") for support.

## 6. Retries policy summary

| Caller | Retries |
|---|---|
| Browser GET queries | 2 (retryable only) |
| Browser mutations | 0 automatic (except CSRF refresh) |
| SSE resume | per `13_STREAMING.md` §7 |
| GroqService | ≤ 2 before first token |
| Embeddings, search provider, sandbox | 1–3 per their docs |
| ARQ jobs | up to 5 with backoff |
| Webhook processing | Razorpay retries delivery; we return 5xx only on transient DB errors |

## 7. Never expose

Stack traces, exception class names, SQL, constraint names (map them), environment variable names/values, internal URLs, other users' identifiers, provider raw error bodies, file system paths. Enforced by: global handlers, response schema validation, and a test that triggers unhandled exceptions and asserts the body matches the generic envelope.
