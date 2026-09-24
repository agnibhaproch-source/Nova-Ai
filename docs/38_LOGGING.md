# 38 — Logging

## 1. Format

All backend processes (api, worker, sandbox-runner) emit **one JSON object per line to stdout** via `structlog`. The platform collects stdout (reference: CloudWatch Logs → OTLP/Loki). Next.js server logs use `pino` with the same field names.

Required fields on every log line:

| Field | Example | Notes |
|---|---|---|
| `timestamp` | `2026-09-24T10:15:30.123Z` | UTC ISO-8601 ms |
| `level` | `info` | debug/info/warning/error/critical |
| `service` | `nova-api` | `nova-api`, `nova-worker`, `nova-web`, `nova-sandbox-runner` |
| `env` | `production` | `APP_ENV` |
| `version` | `1.4.2+sha.abc1234` | build version |
| `event` | `http.request.completed` | dotted, stable identifier (never free text) |
| `request_id` | `01J…` | from `X-Request-ID`; job id in workers |
| `trace_id`, `span_id` | hex | OTel correlation |
| `logger` | `app.services.chat_service` | module |

Contextual fields when available: `user_id` (UUID only — never email), `api_key_id`, `conversation_id`, `message_id`, `file_id`, `job_name`, `latency_ms`, `status_code`, `method`, `route` (template, e.g. `/api/v1/conversations/{conversation_id}`), `error_code`, `error_type`.

## 2. Configuration (`app/core/logging.py`)

```python
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,      # request_id, user_id bound per request
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_service_fields,                          # service, env, version
        add_otel_ids,                                # trace_id, span_id
        redact_sensitive,                            # §5
        structlog.processors.dict_tracebacks,        # structured exceptions (server logs only)
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(LOG_LEVEL),
)
```

Standard library logging (uvicorn, sqlalchemy, httpx, arq) is routed through structlog's `ProcessorFormatter`. `sqlalchemy.engine` at WARNING (never log SQL parameters). `httpx` at WARNING. In development, `LOG_FORMAT=console` enables pretty colored output.

## 3. Levels

| Level | Use |
|---|---|
| debug | Local diagnostics; disabled in production |
| info | Request completion, job completion, business events (login, file ready) |
| warning | Recoverable anomalies: retries, provider 429, degraded mode, validation of external data failed |
| error | Unexpected failures, 5xx, job permanently failed |
| critical | Data integrity risk, secret misconfiguration, service cannot start |

## 4. Standard events

| Event | Level | Key fields |
|---|---|---|
| `http.request.completed` | info (warning ≥ 400 for 429, error ≥ 500) | method, route, status_code, latency_ms, user_id, bytes_out |
| `sse.stream.opened` / `sse.stream.closed` | info | message_id, reason (`complete`, `client_disconnect`, `error`), duration_ms, events_sent |
| `chat.generation.started` / `.completed` / `.failed` / `.cancelled` | info/error | message_id, model_key, ttft_ms, latency_ms, tokens, tool_count, error_code |
| `groq.request.completed` / `.failed` | info/warning | see `14_GROQ_INTEGRATION.md` §12 |
| `tool.call.completed` | info | tool_name, status, latency_ms, error_code |
| `file.processing.completed` / `.failed` | info/error | file_id, extension, stage, duration_ms, error_code |
| `job.completed` / `job.failed` / `job.retrying` | info/warning/error | job_name, job_id, attempt, duration_ms |
| `auth.login.failed` | warning | user_id (if known), reason (`bad_password`, `locked`, `suspended`) — no email |
| `ratelimit.blocked` | info | policy, dimension |
| `billing.webhook.processed` | info | event_type, event_id |
| `security.csrf_failed`, `security.ssrf_blocked`, `security.proxy_secret_invalid` | warning | route, reason |
| `startup.config_invalid` | critical | setting name (never value) |

## 5. Never log

- Secrets: API keys (ours and Groq's), passwords, session tokens, CSRF tokens, reset/verify tokens, Razorpay secrets/signatures, S3 keys, `AUTH_SECRET`, Authorization/Cookie headers.
- User content: message text, prompts, completions, file contents, file names (log `file_id` and extension only), memory content, custom instructions, search queries (log `sha256(query)[:12]` if needed), tool arguments for web_search/code_execution.
- Emails (use `user_id`), phone numbers, full payment payloads.

`redact_sensitive` processor:
1. Drops/masks keys matching `(?i)(pass(word)?|secret|token|api[_-]?key|authorization|cookie|signature|set-cookie|key_secret|dsn)` → `"[REDACTED]"`.
2. Scans string values for patterns (`gsk_[A-Za-z0-9]{20,}`, `nova_sk_[A-Za-z0-9]{20,}`, `rzp_(live|test)_[A-Za-z0-9]+` secret forms, `AKIA[0-9A-Z]{16}`, JWT regex, PEM headers, emails) → masked.
3. Truncates any string value > 2,000 chars.

Unit tests feed known secrets through the logger and assert they never appear in output.

## 6. Request logging middleware

Logs one `http.request.completed` per request after the response (for SSE, after stream close with `sse.stream.closed`). Health check requests are sampled at 1%. Request/response bodies are never logged.

## 7. Audit log vs application log

`audit_logs` (DB) is the durable, queryable, security-relevant trail (retained ≥ 2 years; IPs nulled after 180 days). Application logs are operational (retention 30 days hot, 90 days archive). Audit action names:

`auth.*` (see 09 §15), `user.updated`, `user.deleted`, `user.export.requested`, `user.export.downloaded`, `api_key.created|revoked`, `billing.subscription.created|verified|cancelled|state_changed`, `billing.payment.recorded`, `file.malware_detected`, `admin.user.viewed`, `admin.user.suspended|unsuspended|role_changed|plan_overridden|sessions_revoked`, `admin.content.accessed`, `admin.title.revealed`, `admin.settings.updated`, `admin.model.toggled`, `admin.plan.updated`, `admin.moderation.updated`, `admin.webhook.reprocessed`, `admin.export`, `admin.bootstrap`.

## 8. Frontend logging

- Browser: no console logging in production builds except errors captured by Sentry (`console.error` is patched only in development).
- Next.js server (proxy): `pino` JSON with `request_id`, method, path template, status, latency, upstream latency; never cookies or bodies.
