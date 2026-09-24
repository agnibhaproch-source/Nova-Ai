# ADR 0002 — No email verification step

- Status: accepted
- Date: 2026-09-24
- Supersedes: docs/09 §4 (email verification and unverified-account limits) and every rule that depends on a verified email (docs/10, 18, 31, 32, 35 and the product docs that repeat them)

## Context
The product owner decided that accounts are usable in full right after signup: no verification email, no "verify your email" banners, and screenshots/file uploads work immediately. Before this decision, an unverified account could chat for 24 h (20 messages), and could not upload files (including Quick Chat screenshots), create API keys, subscribe or export data.

## Decision
- Signup no longer sends a verification email. `POST /auth/verify-email` and `POST /auth/verify-email/resend`, the `/verify-email` page and the `verify_email` email template are removed.
- No endpoint checks verification: uploads, chat quota, API keys, billing and exports only apply their normal auth, plan and rate-limit rules. The error codes `EMAIL_NOT_VERIFIED` and `ALREADY_VERIFIED` are removed.
- `email_verified` is dropped from the session principal, the session cache, the `user` API object and the admin users table; the admin analytics funnel no longer has a "verified" step.
- The `users.email_verified_at` column and the `verify_email` value in the `email_tokens.purpose` check constraint stay in the schema (no migration); nothing reads or writes them.
- Password reset by email is unchanged.

## Consequences
- Anyone can sign up with an address they don't own. Signup and per-feature rate limits (docs/33) remain the abuse controls; the free plan's limits cap cost.
- A mistyped email means password reset can't reach the user.
- Reintroducing verification later is additive: the column and the token purpose are still there.
