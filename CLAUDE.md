# CLAUDE.md — NOVA AI

This file is a short entry point. The `docs/` directory is authoritative.

1. **Read `docs/00_MASTER_INSTRUCTION.md` first.**
2. **Read all `docs/*.md` files before major implementation** (a new phase, a new subsystem, schema changes, new dependencies, or cross-service changes). For small changes, read `00`, `55`, `54`, `56`, and the docs for the area you touch.
3. **Treat the documentation as the source of truth.** If code and docs disagree, fix the code, or update the docs deliberately in the same change (with an ADR in `docs/adr/` for architecture changes). Resolve doc conflicts with `00_MASTER_INSTRUCTION.md` §4.
4. **Use Groq only.** All LLM output (chat, titles, summaries, memory extraction, eval judging, STT/TTS) goes through `GroqService` in `apps/api/app/ai/groq/`. Never add OpenAI, Anthropic, Gemini, OpenRouter, Together, Mistral, Cohere, or any other LLM provider or SDK. The browser never calls Groq. Never invent Groq model IDs; they come from configuration.
5. **Never expose secrets.** No keys in code, logs, commits, client bundles, or `NEXT_PUBLIC_*` variables. `GROQ_API_KEY` is server-only. User-supplied Groq keys (BYOK, docs/14 §2a) are accepted only by the API, stored encrypted in Redis per conversation, and never logged, persisted to Postgres, or returned.
6. **Build incrementally** following `docs/53_IMPLEMENTATION_PHASES.md`, phase by phase, feature by feature, end to end.
7. **Test continuously**: `make lint`, `make typecheck`, `make test` (and `make e2e` for user flows) after meaningful changes. Fix failures; never disable tests.
8. **Never fake functionality.** No mock/stub/canned behavior in production code paths. Test doubles live only in test directories. Unavailable features are disabled with an honest UI state.
9. **Preserve existing work.** Inspect code before modifying it; don't rewrite working code outside the task scope.
10. **Consult `docs/56_DEFINITION_OF_DONE.md`** before declaring any feature or phase complete, and update affected docs in the same change.

Quick commands: `make up` · `make check` · `make e2e` · `make api-types` · `make providers-check` (see `docs/44_LOCAL_DEVELOPMENT.md`).
