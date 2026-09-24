# 56 — Definition of Done

## 1. Feature-level Definition of Done

A feature (user story, endpoint, UI flow, job, or tool) is **DONE** only when **every** item applies or is explicitly N/A with justification in the PR:

### Functionality
- [ ] **Frontend exists** for user-facing behavior, including loading, empty, error, and disabled states; responsive at all breakpoints (`28`); keyboard and screen-reader accessible (`27` §16–17, ACC-*).
- [ ] **Backend exists**: router → service → repository/adapters following `54_CODING_STANDARDS.md`.
- [ ] **Persistence exists when required**: Alembic migration (reviewed, expand/contract safe), models, indexes, constraints matching `08_DATABASE_SCHEMA.md`.
- [ ] Behavior matches the relevant spec documents (no undocumented deviations).
- [ ] No mocked/fake/simulated production behavior (`00` R4).

### Security & privacy
- [ ] **Authentication works** (session and, where allowed, API key with correct scopes).
- [ ] **Authorization works**: ownership checks (404 for foreign resources), role checks for admin, CSRF for cookie-authenticated unsafe requests.
- [ ] Input validation at the boundary; output contains no secrets or other users' data.
- [ ] **Secrets are protected**: nothing in code, logs, bundle, or images; new env vars documented in `42` and `.env.example`.
- [ ] Rate limits/quotas applied where the feature consumes shared resources.
- [ ] Audit logging for security-relevant/admin actions; analytics without content.
- [ ] Groq-only rule respected; `make providers-check` passes.

### Quality
- [ ] **Errors are handled**: documented error codes (`32`), user-friendly messages, retries where appropriate, no stack traces exposed.
- [ ] Observability: structured logs with request id, metrics/spans for significant operations.
- [ ] **Tests exist**: unit + integration/API tests for backend logic, authz tests for new resources, component tests for UI, E2E for primary user journeys touched.
- [ ] **Tests pass** (`make test`, relevant `make e2e`); coverage thresholds met (`40` §9).
- [ ] **Lint passes** (`make lint`).
- [ ] **Typecheck passes** (`make typecheck`).
- [ ] **Build passes** (`make build-prod` / CI docker + Next build); bundle secret check and size budget pass.
- [ ] OpenAPI types regenerated (no diff); OpenAPI snapshot updated if the contract changed.
- [ ] AI-affecting changes: eval smoke run attached; no gated regression (`41` §6).

### Documentation & review
- [ ] **Documentation is updated** (all affected docs; ADR for architecture changes; `53` status if a phase completes).
- [ ] PR reviewed and approved per `45_GIT_WORKFLOW.md`; CI green.
- [ ] Deployed to staging and smoke-tested (for merged work).

## 2. Phase-level Definition of Done

A phase is DONE when:
1. All features in the phase meet §1.
2. The phase's acceptance criteria in `53_IMPLEMENTATION_PHASES.md` are demonstrated (checklist in the phase-completion PR, with evidence: test runs, screenshots, metrics).
3. No open P1/P2 bugs for the phase's features.
4. `53` status table updated.

## 3. Product-level Definition of Done (GA)

The entire product is DONE only when **every** required phase (1–11) passes its acceptance criteria **and**:

| Area | Criterion | Source |
|---|---|---|
| Accounts | Signup, verification, login/logout, reset, sessions management, profile, preferences, deletion, export work end-to-end | 09, 10 |
| Chat | Streaming with resume, stop, edit/branches, regenerate, titles, summaries, search, archive/trash/restore, feedback, model selection | 11–16 |
| Groq | Sole LLM provider; retries/fallback/circuit breaker; usage extraction; live nightly smoke green for 14 consecutive days | 14, 15 |
| Files & RAG | All 7 document formats processed; citations accurate per eval gates; isolation tests pass | 18–21 |
| Memory | Extraction precision gate met; full user control | 17 |
| Tools | Calculator, file search, web search, code execution operational with security suites passing (gVisor in production) | 22–24 |
| Multimodal/voice | Enabled exactly as configured; honest disabled states otherwise | 25, 26 |
| UI | All screens in `27` implemented; responsive per `28`; Lighthouse a11y ≥ 95; axe no serious/critical | 27–29 |
| API | Every endpoint in `31` implemented with documented errors; OpenAPI snapshot matches docs | 30–32 |
| Security | `33` controls implemented; pen test high/critical resolved; ZAP baseline clean of high findings | 33 |
| Limits & usage | Rate limits, quotas, cost estimates, global budget operational | 34, 35 |
| Admin | All admin pages in `36` functional with server-side authz and audit | 36 |
| Analytics | Event catalogue implemented with privacy rules | 37 |
| Operations | Logging, monitoring dashboards, alerts with runbooks, SLOs measured | 38, 39 |
| Testing | Coverage thresholds; E2E matrix green; load tests meet NFRs; eval baselines committed | 40, 41 |
| Deployment | Production deployed per `47`; rollback tested; backups + restore drill + DR game day done; RTO/RPO met | 47–50 |
| Billing | Razorpay live mode verified end-to-end with real payment and webhook reconciliation | 31 §12 |
| Cost | Unit economics report produced; cost alerts active | 51 |
| Docs | All docs accurate to the shipped system; no unresolved conflicts | 00 |
