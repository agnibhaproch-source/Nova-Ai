# 45 — Git Workflow

## 1. Branch strategy (trunk-based)

- `main` — always releasable; protected. Deploys to **staging** automatically.
- Short-lived branches from `main`, merged via PR within ≤ 3 days:
  - `feat/<scope>-<slug>` — features (`feat/chat-regenerate`)
  - `fix/<scope>-<slug>` — bug fixes
  - `chore/<slug>`, `refactor/<slug>`, `docs/<slug>`, `test/<slug>`, `perf/<slug>`, `ci/<slug>`
  - `hotfix/<slug>` — urgent production fixes (same flow, expedited review)
- No long-lived `develop` branch. Incomplete features merge behind a `system_settings` feature flag or remain unreachable from UI/routers until complete (never faked).
- Production releases are **tags** on `main` (§6).

## 2. Branch protection (`main`)

- Require PR; ≥ 1 approving review (2 for changes under `app/core/security.py`, `app/api/deps.py`, `app/ai/groq/`, `apps/sandbox-runner/`, `billing`, migrations — enforced via CODEOWNERS).
- Required checks: `ci / backend`, `ci / frontend`, `ci / e2e`, `ci / docker`, `security / scan`, `security / providers`.
- Linear history (squash merge only); branch up to date before merge; no force pushes; signed commits encouraged.

## 3. Commit conventions (Conventional Commits)

```
<type>(<scope>): <imperative summary ≤ 72 chars>

<body: what and why, wrapped at 100>

<footer: BREAKING CHANGE: …, Refs: #123>
```

Types: `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `build`, `ci`, `chore`, `revert`, `security`.
Scopes: `web`, `api`, `worker`, `sandbox`, `db`, `auth`, `chat`, `stream`, `groq`, `rag`, `files`, `memory`, `tools`, `search`, `voice`, `billing`, `admin`, `infra`, `docs`, `evals`.

Examples: `feat(chat): add regenerate with model override`, `fix(stream): prevent duplicate deltas after resume`, `docs(groq): document retry policy`.

Enforced by `commitlint` on PR titles (squash commit message = PR title + body).

## 4. Pull requests

Template (`.github/pull_request_template.md`):

```markdown
## What
## Why
## How (architecture notes; ADR link if any)
## Screenshots / recordings (UI changes: desktop + mobile)
## Checklist
- [ ] Read relevant docs (list): …
- [ ] Tests added/updated; `make check` passes locally
- [ ] Migrations are expand/contract safe (or N/A)
- [ ] Docs updated (list files) or N/A with reason
- [ ] No secrets, no new NEXT_PUBLIC_* vars (or 42 updated)
- [ ] Groq-only rule respected; no new LLM providers
- [ ] Authz/ownership checks for new endpoints; audit logging for admin actions
- [ ] Eval run attached if AI behavior changed
- [ ] Definition of Done (56) satisfied
```

Size guideline: ≤ 500 changed lines (excluding generated files/lockfiles); larger changes split into stacked PRs.

## 5. Code review

Reviewers check, in order: correctness & security (authz, input validation, secrets), architecture conformance (layers, providers), data model/migration safety, tests quality, performance (N+1, indexes), UX states (loading/empty/error), docs updated. Use "Request changes" for blocking issues; `nit:` prefix for non-blocking. Authors respond to every comment. AI-agent-authored PRs receive the same review bar and must state which docs were read.

## 6. Merge & release

- **Merge:** squash merge; delete branch.
- **Versioning:** SemVer `vMAJOR.MINOR.PATCH` for the whole product. MINOR for features, PATCH for fixes, MAJOR for breaking public API (`/api/v2`).
- **Release:** `release-please` (or manual) maintains `CHANGELOG.md` from Conventional Commits; creating tag `vX.Y.Z` on `main` triggers the production deploy workflow (with environment approval).
- **Hotfix:** branch `hotfix/*` from `main`, PR, merge, tag `vX.Y.(Z+1)`.
- **Rollback:** redeploy previous tag (`47_DEPLOYMENT.md` §8).

## 7. Secrets and hygiene

- Never commit secrets, `.env`, credentials, customer data, or production dumps. `.gitignore` includes `.env`, `.env.*` except `.env.example` and `apps/api/.env.test`.
- `gitleaks` pre-commit hook + CI scan on every PR (full history on `main` weekly).
- If a secret is committed: rotate immediately, then purge history (`git filter-repo`) and force-push under admin supervision; record an incident.
- Large binaries: not committed (eval fixtures ≤ 5 MB each; larger via Git LFS in `evals/fixtures/`).

## 8. Generated files

`apps/web/src/lib/api/schema.d.ts`, `uv.lock`, `pnpm-lock.yaml` are committed. CI fails if `make api-types` produces a diff.
