# 01 — Project Vision

## 1. Product vision

**NOVA AI is a fast, trustworthy, private-by-default AI assistant for people who think, write, build, and learn for a living.**

NOVA AI combines Groq's low-latency inference with a production-quality product layer: persistent conversations, grounded answers over the user's own documents, controllable long-term memory, safe tools (web search, calculation, sandboxed code execution), and a polished, responsive interface. The model is rented; the product (reliability, grounding, privacy, UX, and cost discipline) is what we build.

Vision statement for the team:

> "Every answer is fast, every source is visible, and every piece of the user's data is under the user's control."

## 2. Target users

| Segment | Description | Primary need |
|---|---|---|
| Knowledge workers | Analysts, consultants, PMs, writers | Drafting, summarizing, reasoning over documents |
| Developers | Individual engineers, students learning to code | Code explanations, debugging, running snippets |
| Students & researchers | University students, self-learners in India and globally | Explanations with citations, document Q&A |
| Small teams / API users | Indie builders who want a hosted assistant API with usage controls | Programmatic access via API keys |
| Operators (internal) | NOVA AI admins and support staff | Monitoring, abuse handling, billing support |

Initial market focus: India (Razorpay billing, INR pricing) with a globally usable product (English UI first; i18n-ready).

## 3. Product philosophy

1. **Speed is a feature.** Groq enables very low time-to-first-token; the product must not squander it. Target p50 time-to-first-token at the browser ≤ 800 ms for plain chat (see `03_REQUIREMENTS.md` NFR-001).
2. **Grounded over confident.** When answers draw on files or the web, show citations. Prefer saying "I don't know" to fabricating.
3. **User control over data.** Memory is visible, editable, and deletable. Conversations can be exported and deleted. Private content is never sent to analytics.
4. **Safe by construction.** Tools are allow-listed, permissioned, time-boxed, and sandboxed. The model can only request actions; the server decides.
5. **Honest product.** No simulated features. If something is unavailable (e.g., a model lacks vision), the UI says so.
6. **Boring, reliable infrastructure.** PostgreSQL, Redis, S3, containers. Few moving parts, each well understood.
7. **Cost-aware.** Every request is metered; quotas protect both users and the business.

## 4. Primary use cases

1. Ask a question and receive a streamed, markdown-formatted answer with syntax-highlighted code.
2. Continue a conversation days later with full history.
3. Upload a PDF/DOCX/XLSX/PPTX/CSV/TXT/MD and ask questions answered with page-level citations.
4. Ask about current events; the assistant performs a web search and cites sources.
5. Ask for a calculation or data transformation; the assistant runs Python in an isolated sandbox and shows code + output.
6. Edit an earlier message or regenerate a response and navigate between alternative branches.
7. Let the assistant remember stable preferences ("I prefer TypeScript examples") and review/delete them.
8. Speak a question and hear the answer (voice mode).
9. Subscribe to a paid plan via Razorpay for higher limits.
10. Use a personal API key to send messages programmatically.
11. Operators monitor health, usage, cost, errors, and abuse in an admin panel.

## 5. Future direction (beyond the roadmap in `52_ROADMAP.md`)

- Shared workspaces and team plans with shared document collections.
- Projects (conversation folders with shared instructions and files).
- Scheduled tasks/agents running tool sequences.
- Additional tools via a vetted plugin interface (never arbitrary code from third parties in-process).
- Video understanding when supported by configured Groq models.
- Native mobile apps consuming the same `/api/v1`.

## 6. Non-goals

- **Training or fine-tuning foundation models.** NOVA AI consumes Groq-hosted models.
- **Multi-LLM-provider routing.** Groq is the only LLM provider (see `00_MASTER_INSTRUCTION.md` R1). The `LLMProvider` protocol exists for testability and clean boundaries, not to add other vendors.
- **Image generation** in the initial roadmap.
- **Arbitrary internet access from code execution.** The sandbox has no network.
- **Real-time multi-user collaborative editing** of conversations.
- **Storing or reselling user content for training.** Never.
- **Self-hosted on-prem enterprise edition** in the initial roadmap.
- **Copying proprietary ChatGPT branding, assets, or code.** NOVA AI has its own identity.

## 7. Principles (decision tie-breakers)

When trade-offs arise, prefer, in order:

1. Security and privacy
2. Correctness and data integrity
3. Reliability
4. Latency
5. Cost
6. Feature breadth

Additional engineering principles:

- **Server decides.** Clients render state; authorization, quotas, tool execution, and model selection are enforced server-side.
- **Stateless API processes.** All shared state lives in PostgreSQL, Redis, or object storage.
- **Asynchronous heavy work.** Document processing, memory extraction, summarization, exports, and purges run in workers.
- **Configuration over code for volatile facts.** Model IDs, limits, prices, and plan quotas are configuration.
- **Observability from day one.** Every request has a request ID, a trace, structured logs, and usage records.
