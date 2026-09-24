# 33 — Security Specification

Security requirements override convenience (`00_MASTER_INSTRUCTION.md` §4). Target: OWASP ASVS 4.0 Level 2 alignment; OWASP Top 10 (2021) and OWASP Top 10 for LLM Applications addressed below.

## 1. Threat model (summary)

| Asset | Threats | Primary controls |
|---|---|---|
| User accounts | Credential stuffing, session theft, CSRF | Argon2id, rate limits/lockout, HttpOnly cookies, CSRF tokens, session revocation |
| Conversations, files, memories | IDOR / cross-tenant access, leakage via RAG | Owner-scoped repositories, 404 on foreign ids, `user_id` filters in every chunk query, authz test suite |
| Groq API key & secrets | Exposure in client/logs/images | Server-only settings, redaction, bundle scanning, secret manager |
| Infrastructure | SSRF, RCE via code execution/files | SafeFetcher, gVisor sandbox, no parsing in API process, file validation |
| Model behavior | Prompt injection, data exfiltration via tools | Untrusted-data delimiting, tool allow-list, no network in sandbox, no secret access from tools |
| Billing | Forged payment callbacks, replay | Signature verification, webhook idempotency, server-side status confirmation |
| Availability | Abuse, DoS, cost exhaustion | Rate limits, quotas, circuit breakers, request size limits |

## 2. Authentication security

See `09_AUTHENTICATION.md`. Key controls: Argon2id; 256-bit session tokens hashed with SHA-256; HttpOnly/Secure/SameSite=Lax cookies; absolute + idle expiry; revocation on password change; login lockout; generic credential errors; no user enumeration on reset; Origin checks on pre-session POSTs; session fixation prevented (new token on every login).

## 3. Authorization

- Default-deny: every router declares its auth dependency; a test enumerates all routes and asserts each has an explicit auth dependency (or is on the allow-list of public routes: healthz, readyz, signup, login, password forgot/reset, billing/plans, app-config, webhooks/razorpay, analytics/events).
- Owner-scoped repository methods; cross-tenant access returns 404.
- Admin authorization server-side on every request; support role read-only.
- API key scopes enforced per endpoint; API keys cannot access account-security, billing, API-key, or admin endpoints.

## 4. OWASP Top 10 mapping

| Risk | Controls |
|---|---|
| A01 Broken Access Control | §3; authz integration tests for every resource type; 404 semantics |
| A02 Cryptographic Failures | TLS 1.2+ everywhere (HSTS `max-age=63072000; includeSubDomains; preload`), Argon2id, HMAC-SHA256 for tokens/keys, encryption at rest (managed Postgres, S3 SSE, Redis TLS in prod) |
| A03 Injection | SQLAlchemy bound params; no raw SQL string building; Pydantic validation; no shell execution of user input; `trafilatura`/parsers run on data only |
| A04 Insecure Design | Threat model, tool allow-list, sandbox isolation, quotas |
| A05 Security Misconfiguration | Settings validation per env (refuse insecure config in prod: `Secure` cookies, `GROQ_BASE_URL` unset, debug off, docs disabled), security headers, minimal images |
| A06 Vulnerable Components | Dependabot, pip-audit, pnpm audit, Trivy; lockfiles; pinned base image digests |
| A07 Identification & Auth Failures | §2 |
| A08 Software & Data Integrity | Signed commits encouraged; CI-built images only; webhook signatures; no deserialization of untrusted pickles (no `pickle` anywhere) |
| A09 Logging & Monitoring Failures | Audit logs, structured logs, alerts (`38`, `39`) |
| A10 SSRF | §7 |

## 5. XSS

- React escapes by default; `dangerouslySetInnerHTML` is forbidden (ESLint `react/no-danger` error) except in the KaTeX renderer path controlled by `rehype-katex` output (trusted library output from sanitized math input with `trust: false`, `strict: "warn"`, `maxExpand: 1000`).
- Markdown: `react-markdown` without `rehype-raw`; allowed URL protocols for links: `http`, `https`, `mailto` (custom `urlTransform`); images in markdown not rendered.
- SVG uploads rejected; user files never served inline except raster images via `<img>` from presigned URLs on the storage domain (separate origin).
- CSP (set in `middleware.ts` with per-request nonce):
  ```
  default-src 'self';
  script-src 'self' 'nonce-{nonce}' 'strict-dynamic' https://checkout.razorpay.com;
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: blob: {S3_PUBLIC_HOST};
  media-src 'self' blob:;
  connect-src 'self' {SENTRY_INGEST_HOST} {S3_PUBLIC_HOST};
  frame-src https://api.razorpay.com https://checkout.razorpay.com;
  font-src 'self';
  object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests
  ```
  `{S3_PUBLIC_HOST}` is the origin of `S3_PUBLIC_ENDPOINT`; `{SENTRY_INGEST_HOST}` is the origin derived from `NEXT_PUBLIC_SENTRY_DSN` (both computed in `middleware.ts`, not separate env vars).
  (`style-src 'unsafe-inline'` is required by some Radix/Framer runtime styles; revisit with nonces when feasible.) Verify Razorpay's documented CSP requirements when implementing billing.
- Other headers: `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(self), geolocation=(), payment=(self "https://checkout.razorpay.com")`, `Cross-Origin-Opener-Policy: same-origin`.

## 6. CSRF

Double-submit token bound to session via HMAC + Origin verification (`09_AUTHENTICATION.md` §10). SameSite=Lax cookies. No state-changing GET endpoints (lint rule in router review checklist; test asserts all GET handlers are side-effect free except `last_seen` touches and download redirects).

## 7. SSRF

All server-initiated fetches to user- or model-influenced URLs go through `SafeFetcher` (`app/search/fetcher.py`):

1. Parse URL; scheme must be `http`/`https`; port ∈ {80, 443, 8080, 8443}; no userinfo.
2. Resolve DNS (async `getaddrinfo`) and reject if **any** resolved address is private, loopback, link-local, multicast, reserved, CGNAT (100.64.0.0/10), unique-local IPv6, IPv4-mapped private, or cloud metadata (169.254.169.254, fd00:ec2::254).
3. Connect to the **validated IP** (custom httpx transport pins the resolved address and sets SNI/Host header) — prevents DNS rebinding.
4. Redirects followed manually (max 3), re-validating each hop.
5. Timeouts: connect 3 s, total 5 s; max body 2 MB (streamed, abort beyond); only `text/html`, `text/plain`.
6. No cookies, no auth headers, fixed User-Agent.
7. Egress in production additionally restricted: worker/API egress through a NAT with network policy denying RFC1918 destinations except explicitly allowed internal services.

Other outbound calls (Groq, Razorpay, embeddings, search provider, sandbox runner, SMTP) use fixed configured hosts only.

## 8. Prompt injection and LLM-specific risks

| Risk (OWASP LLM) | Control |
|---|---|
| LLM01 Prompt injection (direct/indirect) | Untrusted content (documents, web pages, tool output, memories, summaries) is wrapped in labeled delimiters and the system prompt declares it data; delimiter tokens inside data are neutralized; tools cannot perform privileged actions (no email sending, no account changes, no data deletion, no cross-user access); the model cannot choose its own permissions |
| LLM02 Insecure output handling | Output rendered as sanitized markdown; never executed; links `nofollow`; code executes only when the model calls the sandbox tool |
| LLM06 Sensitive information disclosure | Context contains only the requesting user's data; system prompt contains no secrets; memory filter rejects credentials |
| LLM07 Insecure plugin/tool design | Strict JSON schemas, validation, allow-list registry, per-tool quotas/timeouts |
| LLM08 Excessive agency | Max 5 tool iterations, 8 tool calls per turn; tools are read-only except code execution (sandboxed, no network) |
| LLM09 Overreliance | Citations, UI disclaimer, uncertainty instructions |
| LLM10 Model theft / abuse | Quotas, rate limits, abuse detection, API keys scoped |

Exfiltration via rendered content: markdown images are not rendered (no tracking pixels); links require a user click; web search queries pass through the sensitive-data filter.

## 9. Secret management

- Local: `.env` (git-ignored); `.env.example` has placeholders only.
- Deployed: platform secret manager (reference: AWS Secrets Manager → ECS task secrets; Vercel encrypted env vars for web). Secrets injected as env vars at runtime, never baked into images (`docker history` must show no secrets; CI Trivy secret scan).
- Rotation: `AUTH_SECRET` rotation supported via `AUTH_SECRET_PREVIOUS` (verification accepts both for CSRF/API-key HMAC during a 7-day window; API keys hashed with the previous secret are re-hashed on successful use). `GROQ_API_KEY`, `RAZORPAY_*`, `S3_*` rotated at least every 180 days or on suspicion.
- Git: gitleaks pre-commit hook + CI; history rewrite + rotation if a secret is ever committed.
- `Settings` uses `SecretStr` for secrets; `repr` never prints them.
- Only `NEXT_PUBLIC_*` variables reach the browser; allowed public vars are enumerated in `42_ENVIRONMENT_VARIABLES.md`; CI script `scripts/check_bundle_secrets.sh` greps built `.next/static` for secret patterns (`gsk_`, `nova_sk_`, `rzp_live_`/secret forms, AWS keys, PEM).

## 10. API key security

Prefix + 238-bit random body; HMAC-SHA256 hashed at rest; shown once; scoped; optional expiry; revocable; last-used tracking; per-key rate limits; keys never logged (log `key_prefix` only); leaked-key response: revoke + notify user email.

## 11. File attack defenses

Extension/MIME/magic validation, size limits, zip-bomb checks, image pixel limits, macro rejection, ClamAV scanning, parsing in isolated worker subprocesses with memory limits, private bucket, presigned short-lived URLs, `Content-Disposition: attachment`, random storage keys, no user-controlled paths (`18_FILE_UPLOADS.md`, `19_DOCUMENT_PROCESSING.md`).

## 12. Payment security

- Checkout handled by Razorpay (PCI scope stays with Razorpay).
- Client-reported success is never trusted alone: server verifies signature **and** fetches the subscription from Razorpay API before activating.
- Webhooks: HMAC verification over the raw body, constant-time compare, idempotent by event id, state machine allows only forward transitions, amounts/plan ids cross-checked against `plans`.
- Razorpay secrets server-only; `NEXT_PUBLIC_RAZORPAY_KEY_ID` (public key id) is the only Razorpay value in the browser (the key id is returned by the API as well).

## 13. Sandbox security

See `24_CODE_EXECUTION.md`: gVisor, no network, read-only rootfs, tmpfs, dropped capabilities, no-new-privileges, non-root, resource limits, per-execution containers, isolated hosts without secrets, runner auth token.

## 14. Logging security

- Redaction processor removes keys matching `password|secret|token|api_key|authorization|cookie|signature|key_secret` (case-insensitive) and values matching secret patterns.
- Never log message content, file content, memory content, prompts, completions, search queries (hash only), or full IPs in analytics.
- Sentry: `send_default_pii=False`; `before_send` scrubs request bodies, cookies, headers except allow-list; breadcrumbs for HTTP include method/path only.
- Audit logs append-only (DB grants).

## 15. Data privacy

Data minimization, retention jobs (`07_DATABASE_ARCHITECTURE.md` §13), export/deletion (`10_USER_SYSTEM.md`), no training use, subprocessors documented (Groq, hosting, Razorpay, email provider, search provider). Encryption in transit and at rest. Admin content access requires reason + audit.

## 16. Abuse prevention

- Rate limits and quotas (`34`, `35`).
- Signup protections: per-IP limits, disposable-email domain blocklist (`app/core/data/disposable_domains.txt`, admin-toggleable setting `block_disposable_emails`).
- Automated flags: excessive rate-limit hits (> 100/hour), sandbox abuse, malware uploads, payment fraud signals (multiple failed payments) → `moderation_flags`.
- Admin actions: suspend user (revokes sessions/API keys), block domains via settings.
- Groq cost protection: global daily token budget `system_settings.global_daily_token_budget`; when 90% consumed → alert; at 100% → free-plan chat paused with `SERVICE_DEGRADED` message (paid plans continue until 120%).

## 17. Security testing

`40_TESTING.md` §6: authz matrix tests, CSRF tests, SSRF tests (internal IPs, DNS rebinding simulation, redirects), XSS rendering tests (malicious markdown corpus), upload fuzz corpus, sandbox escape tests, webhook signature tests, secret-in-bundle check, dependency scans, OWASP ZAP baseline scan against staging (nightly).

## 18. Incident response

Runbook `docs/runbooks/security-incident.md` (created in Phase 11): triage, containment (revoke keys/sessions, rotate secrets, disable features via settings), eradication, recovery, user notification within 72 h where legally required (India DPDP Act 2023 obligations reviewed by legal), post-mortem.
