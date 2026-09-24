# 52 — Roadmap

Phases are sequential by dependency; later phases may start in parallel only when their dependencies (listed in `53_IMPLEMENTATION_PHASES.md`) are complete. MVP = Phases 1–4.

| Phase | Name | Outcome | Key docs |
|---|---|---|---|
| 1 | **Foundation** | Monorepo, Docker dev stack, CI, FastAPI/Next.js skeletons, DB + migrations, auth (signup/login/logout/sessions/verify/reset), user profile & preferences, BFF proxy, error handling, logging, telemetry, rate-limit framework, audit logs, admin shell (users list), staging deploy | 04–10, 30–34, 38, 42–47 |
| 2 | **Chat** | Conversations, message tree, Groq integration, streaming SSE with resume/cancel, context management (without memory/RAG), titles, summaries, markdown/code UI, edit/regenerate/branches, search, feedback, model picker, usage tracking + quotas, admin usage/dashboard basics | 11–16, 27–29, 35–37 |
| 3 | **Files** | Upload pipeline (presigned), validation, malware scanning, library UI, attachments to conversations, download/delete, image uploads stored (vision use comes in Phase 9) | 18 |
| 4 | **RAG** | Document extraction for all formats, chunking, embeddings (TEI), pgvector, hybrid retrieval, citations UI, source panel, `/rag/search` | 19–21 · **MVP complete** |
| 5 | **Memory** | Long-term memory extraction, retrieval, management UI, privacy filters | 17 |
| 6 | **Tools** | Tool framework (registry, engine, persistence, UI), calculator, file_search | 22 |
| 7 | **Search** | Web search tool with SearXNG/Brave adapters, SafeFetcher, citations | 23, 33 §7 |
| 8 | **Code execution** | Sandbox runner + image, gVisor production hosts, code_execution tool and UI | 24 |
| 9 | **Voice** (+ multimodal images) | STT dictation, voice mode, read aloud (Groq STT/TTS or browser TTS), vision image input when a vision model is configured, capabilities endpoint | 25, 26 |
| 10 | **Billing** (+ API access) | Plans UI, Razorpay subscriptions/checkout/webhooks, plan enforcement, payments history, API keys, product analytics dashboards | 31 §12–14, 35, 37 |
| 11 | **Production scaling** | Terraform, full admin panel (health, errors, moderation, settings, models, plans), dashboards/alerts/runbooks, load testing gates, backups & DR drills, partitioning readiness, performance tuning, security hardening (ZAP, pen test), launch checklist | 36, 39, 47–51 |

## Post-roadmap (future, unscheduled)

- OCR for scanned PDFs (self-hosted OCR engine).
- Projects/folders with shared instructions and files.
- Conversation sharing (read-only links with redaction).
- Team workspaces and team billing.
- Realtime duplex voice (WebSocket).
- Video understanding (when supported by configured Groq models).
- Social login (Google) and email change flow.
- Additional locales (Hindi UI first).
- Native mobile apps.
- Cross-encoder reranking; per-user hash partitioning at S4.

## Milestones

| Milestone | Definition |
|---|---|
| M1 Internal alpha | Phase 2 complete on staging; team dogfooding |
| M2 Private beta (MVP) | Phase 4 complete; 100 invited users; free plan only |
| M3 Public beta | Phases 5–8 complete; signups open with limits |
| M4 Paid launch | Phases 9–10 complete; Razorpay live mode |
| M5 GA | Phase 11 complete; SLOs met for 30 days |
