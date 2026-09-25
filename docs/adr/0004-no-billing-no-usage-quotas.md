# 0004 — No billing and no usage quotas: the Groq key is the only limit
- Status: accepted
- Date: 2026-09-25
- Deciders: product owner
- Supersedes: paid plans and Razorpay billing (docs/31 §12, docs/53 Phase 10), and the quota enforcement in docs/35 §6

## Context
NOVA AI is run for personal use, not sold. Each conversation already runs on the user's own Groq API key (ADR 0001), so Groq enforces its own per-key rate limits and bills the key owner directly. On top of that, Nova enforced its own plan quotas: 50 messages a day and 500,000 tokens a month on the free plan, plus daily caps on web searches, code runs, voice minutes and uploads, shorter replies and messages, and tight per-minute chat rate limits. Billing (Razorpay) was the only way past them, and it was never configured. The result was that a user could not use their own Groq key up to its real limits.

## Decision
- **Billing is removed.** The `/billing/*` and `/webhooks/razorpay` endpoints, `BillingService`, the `billing_maintenance` cron, admin subscriptions/payments/webhook-event endpoints, the `razorpay` dependency and `RAZORPAY_*` settings are deleted. The web pricing page, billing settings, admin billing page and the Razorpay CSP entries are deleted.
- **No usage quotas.** Nova no longer counts or caps messages per day, tokens per month, web searches, code executions, voice minutes or uploads per day. `QuotaService` keeps only `plan_limits` (capability settings) and `usage_totals` (informational).
- **Every plan gets the same, most generous limits** (migration `0016_no_usage_quotas`): all models, API access, 100,000-character messages, the former `pro` file and storage sizes, and a plan output cap above every model's own limit (so replies are bounded only by `config/models.yaml`).
- **Per-minute rate limits are the same for every plan** and set above Groq's own per-key limits (docs/34 §4). They remain as abuse guards only.
- **The Usage page shows the Groq key's real limits.** `GroqProvider` reads Groq's `x-ratelimit-*` response headers (requests per day, tokens per minute, remaining, reset) with the SDK's `with_raw_response`; `GroqService` stores the latest snapshot per (user, model) in Redis (`nova:{env}:groqrl:{user_id}`, 7-day TTL). `GET /usage/current` (replaces `GET /usage/quota`) returns it with the user's usage totals.

## Consequences
- Positive: the only ceiling is the user's Groq key; Groq's own 429s surface as `PROVIDER_RATE_LIMITED`, as before.
- Positive: less code and no payment surface to secure.
- Negative: no protection against one user spending a lot of a shared server key in `GROQ_KEY_MODE=server`; `system_settings.global_daily_token_budget` (docs/35 §7) remains available for that.
- The `plans`, `subscriptions`, `payments` and `payment_webhook_events` tables are kept (not dropped) so no data is destroyed and the change is reversible; they are no longer written. `users.plan_key` and the `free`/`plus`/`pro` plan rows still exist but no longer differ.
- The `usage` SSE event no longer carries a `quota` object.
- Groq's daily token limit is not reported in response headers, so the Usage page links to Groq's console for it.

## Alternatives considered
- Raise the free plan's quotas to very high numbers: keeps the counters and billing code for no benefit.
- Move the account to `pro`: still capped (2,000 messages a day, 20M tokens a month).

## Docs updated
13 (usage event), 27 (§11–§13), 31 (§11, §12), 32 (payment codes), 34 (§4), 35 (§5–§8), 36 (billing pages), 42 (Razorpay vars), 53 (Phase 10), runbooks (billing-webhooks removed).
