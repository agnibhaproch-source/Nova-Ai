# AGENTS.md — Instructions for coding agents

Applies to every automated coding agent (Claude Code, Codex, Copilot agents, etc.) working in this repository. The full rules are in `docs/00_MASTER_INSTRUCTION.md` and `docs/55_AI_CODING_RULES.md`; this file summarizes them.

## Required reading
- Always: `docs/00_MASTER_INSTRUCTION.md`, `docs/55_AI_CODING_RULES.md`, `docs/54_CODING_STANDARDS.md`, `docs/56_DEFINITION_OF_DONE.md`.
- Before major implementation: every file in `docs/`.
- Before touching an area: its subsystem doc (index in `docs/00_MASTER_INSTRUCTION.md` §8).

## Non-negotiable rules
1. Documentation is the source of truth; conflicts are resolved per `docs/00_MASTER_INSTRUCTION.md` §4.
2. **Groq is the only LLM provider**, accessed only via `GroqService` (`apps/api/app/ai/groq/`). No other LLM SDKs or APIs. The browser never calls Groq.
3. Never expose or commit secrets; only allow-listed `NEXT_PUBLIC_*` variables reach the browser.
4. Never invent external APIs or Groq model IDs; verify against official docs/SDKs; model IDs come from env/config.
5. No fake, mocked, or simulated functionality in production code.
6. Follow the layered architecture (router → service → repository/adapter); no bypasses.
7. Do not change technologies or architecture without an ADR and doc updates in the same change.
8. Do not rewrite working code outside your task.
9. Enforce authentication, ownership authorization, CSRF, and rate limits on every new endpoint.
10. Execute user/model code only through the sandbox runner.

## Workflow
1. Read docs → inspect existing code → confirm the current phase (`docs/53_IMPLEMENTATION_PHASES.md`).
2. Implement end-to-end (migration, backend, API, generated types, frontend, tests, docs).
3. Verify: `make lint && make typecheck && make test`; `make e2e` for user flows; `make api-types` (no diff); `make providers-check`.
4. Fix errors at their cause; never skip or weaken tests.
5. Update docs you affected; check `docs/56_DEFINITION_OF_DONE.md`.
6. Report honestly: what changed, docs read/updated, commands run with results, open issues.

## Asking for help
Ask a human only for irreversible, security-relevant, cost-relevant, or product decisions not covered by the docs. Otherwise make the smallest architecture-consistent decision and document it.
