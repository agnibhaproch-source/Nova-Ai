# 09 — Authentication & Authorization

## 1. Overview

NOVA AI uses **server-side sessions** stored in PostgreSQL (cached in Redis), referenced by an opaque random token in an **HttpOnly cookie**. No JWTs are used for browser auth. Programmatic clients use **API keys** (`Authorization: Bearer nova_sk_...`). OAuth/social login and email change are out of scope for v1 (future; users contact support to change email).

Principals:

| Auth method | Credential | CSRF required | Allowed endpoints |
|---|---|---|---|
| `session` | `nova_session` cookie | Yes, for POST/PUT/PATCH/DELETE | All except those restricted to API keys (none) |
| `api_key` | `Authorization: Bearer nova_sk_…` | No | Endpoints whose scope requirement is satisfied; never `/auth/*`, `/users/me/*` account-security endpoints, `/billing/*`, `/api-keys/*`, `/admin/*` |

## 2. Password policy and hashing

- Length 12–128 characters (Unicode allowed; normalize with NFKC before hashing).
- Reject if in the bundled common-password list (`apps/api/app/core/data/common_passwords.txt`, top 100k, loaded into a `frozenset` at startup) or if it contains the email local-part (case-insensitive, local-part ≥ 4 chars).
- No composition rules (NIST SP 800-63B).
- Hash: Argon2id via `argon2.PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)`.
- On successful login, if `ph.check_needs_rehash(hash)` → rehash and update.
- Hashing runs in a thread (`anyio.to_thread.run_sync`) to avoid blocking the event loop.
- When the user does not exist, verify against a precomputed dummy hash to equalize timing.

## 3. Signup — `POST /api/v1/auth/signup`

Request: `{ "email": str, "password": str, "display_name": str, "accept_terms": true }`

Steps:
1. Rate limit: `auth_signup` policy (5/hour per IP) — `34_RATE_LIMITING.md`.
2. Origin check (§10.3). Reject if `system_settings.signups_enabled = false` → `403 SIGNUPS_DISABLED`.
3. Validate: email via `email-validator` (no DNS check in request path), lower-case domain; password policy; `display_name` trimmed 1–80; `accept_terms` must be `true`.
4. In one transaction: check existing active user with that email → `409 EMAIL_ALREADY_REGISTERED` (accepted enumeration trade-off, mitigated by strict signup rate limit); insert `users` (plan_key `free`), `user_preferences` (defaults); create session (§5); insert `audit_logs(action='auth.signup')`.
5. After commit: record analytics `signup` (no verification email; ADR 0002).
6. Response `201` with `{data: {user}}` and `Set-Cookie` for `nova_session` and `nova_csrf`.

Bootstrap admin: if `ADMIN_BOOTSTRAP_EMAIL` matches the signing-up email **and** no admin exists, role is set to `admin` (audited `admin.bootstrap`).

## 4. Email verification — removed

There is no email verification step (ADR 0002). Accounts are fully usable right after signup; no endpoint checks verification. `users.email_verified_at` and the `verify_email` token purpose remain in the schema, unused.

## 5. Login — `POST /api/v1/auth/login`

Request: `{ "email": str, "password": str }`

1. Rate limits: `auth_login_ip` (20/15 min per IP) and `auth_login_email` (10/15 min per normalized email). Exceeded → `429 RATE_LIMITED`.
2. Load user by email where `deleted_at IS NULL`.
3. If user `locked_until > now()` → `423 ACCOUNT_LOCKED` with `retry_after` seconds (message does not reveal whether the password was correct).
4. Verify password (dummy hash if no user). Failure → increment `failed_login_count`; if ≥ 10 within the window (tracked in Redis `nova:{env}:loginfail:{user_id}` TTL 15 min) set `locked_until = now()+15 min`; audit `auth.login.failed`; return `401 INVALID_CREDENTIALS`.
5. If `status='suspended'` → `403 ACCOUNT_SUSPENDED`.
6. Success: reset counters, `last_login_at=now()`, rehash if needed, create session, audit `auth.login.succeeded`, analytics `login`.
7. Response `200 {data:{user}}` + cookies.

### Session creation

```python
token = secrets.token_urlsafe(32)                 # 256 bits
token_hash = hashlib.sha256(token.encode()).digest()
session = Session(user_id=..., token_hash=token_hash,
                  expires_at=now + timedelta(days=settings.SESSION_TTL_DAYS),
                  ip_address=client_ip, user_agent=ua[:512], device_label=parse(ua))
```

Cookies:

| Cookie | Value | Attributes |
|---|---|---|
| `nova_session` | `token` | `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=SESSION_TTL_DAYS*86400; Domain=COOKIE_DOMAIN (if set)` |
| `nova_csrf` | `base64url(HMAC_SHA256(AUTH_SECRET, "csrf:" + session_id))` | `Secure; SameSite=Lax; Path=/; Max-Age` same; **not** HttpOnly (JS reads it) |

`Secure` is omitted only when `APP_ENV=development` and `APP_URL` is `http://localhost*`. Cookies are set by FastAPI; the Next.js proxy passes `Set-Cookie` through unchanged (same origin).

Maximum 50 active sessions per user; creating the 51st revokes the oldest (`revoked_reason='expired_idle'`).

## 6. Session resolution (every request)

Dependency `get_principal()` in `app/api/deps.py`:

1. If `Authorization: Bearer nova_sk_...` present → API key path (§12). If `Authorization` present with any other scheme → `401 AUTH_INVALID`.
2. Else read `nova_session` cookie; missing → anonymous principal (endpoints requiring auth raise `401 AUTH_REQUIRED`).
3. `h = sha256(token)`; Redis `GET nova:{env}:session:{hex(h)}` (JSON `{session_id,user_id,role,status,plan_key,expires_at,last_seen_at}`, TTL 60 s). Miss → DB join `sessions ⨝ users` where `token_hash=h AND revoked_at IS NULL AND expires_at > now() AND users.deleted_at IS NULL` → cache.
4. Reject if expired, revoked, user not `active` → `401 AUTH_REQUIRED` and clear cookies.
5. Idle timeout: if `last_seen_at < now() - SESSION_IDLE_TIMEOUT_DAYS` → revoke (`expired_idle`) → `401`.
6. If `last_seen_at` older than 5 min → update asynchronously (fire-and-forget task with its own session).
7. Attach `Principal(user_id, role, plan_key, session_id, api_key_id=None, scopes=ALL, auth_method='session')` to `request.state.principal`; bind `user_id` to log context and OTel span attribute `enduser.id`.

## 7. Logout — `POST /api/v1/auth/logout`

Session + CSRF required. Sets `revoked_at=now()`, `revoked_reason='logout'`, deletes the Redis cache key, clears both cookies (`Max-Age=0`), audit `auth.logout`. Idempotent: returns `204` even if already revoked.

## 8. Password reset and change

**Forgot:** `POST /api/v1/auth/password/forgot {email}` → always `202` (no enumeration). If an active user exists: invalidate previous unconsumed reset tokens, create token (60 min), enqueue email with `{APP_URL}/reset-password?token=...`. Rate limit 3/hour per email and 10/hour per IP.

**Reset:** `POST /api/v1/auth/password/reset {token, new_password}` → validate token and policy → in one transaction: update hash, `password_changed_at=now()`, consume token, **revoke all sessions** (`password_changed`), reset lockout, audit `auth.password.reset`. Returns `204`; user must log in again.

**Change:** `POST /api/v1/users/me/password {current_password, new_password}` (session + CSRF) → verify current → update → revoke all **other** sessions → audit `auth.password.changed` → `204`.

## 9. Session expiration and revocation

| Trigger | Effect |
|---|---|
| Absolute TTL (`SESSION_TTL_DAYS`, default 30) | Session invalid after `expires_at` |
| Idle (`SESSION_IDLE_TIMEOUT_DAYS`, default 7; fixed 12 h for `support`/`admin` roles) | Revoked on next use |
| Logout | Current session revoked |
| User revokes a session | `DELETE /users/me/sessions/{id}` |
| "Sign out other devices" | `POST /users/me/sessions/revoke-others` |
| Password change/reset | Others / all revoked |
| Admin suspend or revoke | All revoked (`admin_revoked` / `account_suspended`) |
| Account deletion | All revoked (`account_deleted`) |

Every revocation deletes the Redis cache key(s) (`token_hash` is on the row) so revocation is effective immediately (≤ one in-flight request).

## 10. CSRF strategy

### 10.1 Cookie-authenticated unsafe requests
For `POST, PUT, PATCH, DELETE` with `auth_method='session'`, dependency `require_csrf`:
1. Read header `X-CSRF-Token` and cookie `nova_csrf`; both present and equal (constant-time).
2. Recompute `expected = base64url(HMAC(AUTH_SECRET, "csrf:" + principal.session_id))`; header equals expected.
3. `Origin` header (or `Referer` origin if Origin absent) must equal `APP_URL` origin.
Failure → `403 CSRF_FAILED`.

### 10.2 Frontend
`lib/api/client.ts` reads `nova_csrf` via `document.cookie` and sets `X-CSRF-Token` on every unsafe request, including SSE POSTs.

### 10.3 Pre-session endpoints
`/auth/signup`, `/auth/login`, `/auth/password/forgot`, `/auth/password/reset` have no session; they require `Origin` = `APP_URL` origin (browser requests) and are protected by `SameSite=Lax` + rate limits. Login-CSRF is mitigated because login responses rotate the session.

### 10.4 Exempt
API-key requests (no ambient credentials) and `/api/v1/webhooks/razorpay` (signature-verified).

## 11. Authentication dependencies (FastAPI)

```python
async def get_principal(request) -> Principal            # anonymous allowed
async def require_user(p = Depends(get_principal)) -> Principal   # 401 if anonymous
def require_scopes(*scopes: str)                         # API keys must include scopes; sessions pass
def require_role(*roles: Literal["support","admin"])      # 403 FORBIDDEN otherwise
async def require_csrf(request, p = Depends(require_user))
def require_session_auth()                               # rejects API keys (account/billing/admin endpoints)
```

Routers declare dependencies explicitly per endpoint; `31_API_ENDPOINTS.md` lists them.

## 12. API key authentication

- Format: `nova_sk_` + 40 base62 chars (≈ 238 bits). Generated with `secrets.choice` over base62.
- Stored: `key_prefix` (first 16 chars), `key_hash = HMAC_SHA256(AUTH_SECRET, full_key)`.
- Resolution: compute hash → lookup `api_keys` where `key_hash = h AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())` joined with active user (Redis cache 60 s keyed by hash hex) → `Principal(auth_method='api_key', scopes=row.scopes, api_key_id=row.id)`.
- Invalid → `401 AUTH_INVALID` (constant-time path; rate limited per IP `api_key_auth_fail` 30/min).
- `last_used_at`/`last_used_ip` updated at most once per minute.

## 13. Authorization

### 13.1 Roles
| Role | Capabilities |
|---|---|
| `user` | Own resources only |
| `support` | Read-only admin: users (metadata), usage, subscriptions, payments, health, moderation (can change flag status), audit logs. Cannot change roles/settings, cannot read content. |
| `admin` | All support capabilities + mutate users (suspend, role, plan override), system settings, model enablement, content access with reason |

### 13.2 Ownership enforcement
- Repositories expose owner-scoped methods only: `ConversationRepository.get_for_user(user_id, conversation_id)`; there is **no** unscoped `get(id)` on user-owned repositories (admin repositories are separate modules under `repositories/admin/`).
- Not found or not owned → `404 RESOURCE_NOT_FOUND`.
- Composite checks: attaching a file to a conversation verifies both are owned by the principal; message operations verify `messages.user_id`.
- Admin endpoints use `AdminService` with explicit role checks and audit logging.

### 13.3 Next.js route protection
- `src/middleware.ts`: if path is under `(app)` or `(admin)` and `nova_session` cookie is absent → redirect `/login?next=<path>` (UX only, not security).
- `(app)/layout.tsx` (server component) calls `GET {API_INTERNAL_URL}/api/v1/auth/session` forwarding the cookie and proxy secret; on 401 → redirect to login; passes the user to the client via React context.
- `(admin)/admin/layout.tsx` additionally requires `role ∈ {support, admin}` else `notFound()`.
- Real enforcement always happens in FastAPI.

## 14. Session info endpoint

`GET /api/v1/auth/session` → `200 {data:{user:{id,email,display_name,avatar_url,role,plan_key,onboarding_completed}, session:{id,expires_at}}}` or `401 AUTH_REQUIRED`. Also re-issues `nova_csrf` cookie if missing.

## 15. Audit events

`auth.signup`, `auth.login.succeeded`, `auth.login.failed`, `auth.logout`, `auth.lockout`, `auth.password.reset_requested`, `auth.password.reset`, `auth.password.changed`, `auth.session.revoked`, `auth.sessions.revoked_others`, `api_key.created`, `api_key.revoked`, `admin.bootstrap`.
