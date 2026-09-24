# ADR 0001 — Per-conversation user-supplied Groq keys (BYOK)

- Status: accepted
- Date: 2026-09-24
- Supersedes: the single server-held `GROQ_API_KEY` as the only credential (docs/14 §2)

## Context
The product owner requires that each user supply their own Groq API key when starting a new chat, with `openai/gpt-oss-120b` as the model. The original design assumed one server key. Hard constraints remain: Groq is the only LLM provider, the browser never calls Groq, and keys never reach client bundles, logs or the database.

## Decision
- `GROQ_KEY_MODE=user` (default): `POST /conversations` requires `groq_api_key`; the API validates it with an authenticated `GET /models`, then stores it AES-GCM-encrypted in Redis keyed by conversation id with a sliding TTL. All Groq calls for that conversation (chat, tools loop, titles, summaries, memory extraction) run under that key via a `ContextVar` read by `get_groq_client()`.
- `GROQ_KEY_MODE=server` keeps the original single-key behaviour.
- Voice (not conversation-scoped) requires server mode; in BYOK mode STT is disabled and TTS falls back to the browser.
- Per-key failures (invalid key, per-key rate limit) do not trip the shared per-model circuit breaker.

## Consequences
- Keys pass through the browser once (the user types them) and the BFF, over the existing authenticated, CSRF-protected path. They are never returned.
- Losing Redis loses keys; users are asked to re-enter them (acceptable: Redis is not a system of record).
- Cost estimates in admin reflect the user's own Groq spend, not the operator's.
- Startup model verification only runs in server mode; model facts for `openai/gpt-oss-120b` are pinned in `config/models.yaml` and were verified from Groq's model page.
