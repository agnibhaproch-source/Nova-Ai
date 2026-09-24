# NOVA AI

NOVA AI is a ChatGPT-style AI assistant you can run yourself: a website, a floating **Quick Chat**
popup, a **desktop app** for macOS, Windows and Linux, and a browser extension. It streams answers,
keeps your chat history, reads screenshots and documents, remembers your preferences, and can run
code in a sandbox.

**All AI answers come from [Groq](https://groq.com).** Groq is the only AI provider, and only the
server talks to it; the browser and the desktop app never do. Each user pastes their own Groq API
key when they start a chat. The key is stored encrypted on the server, used only for that chat,
and never shown again.

---

## Contents

1. [Features](#features)
2. [How it's built](#how-its-built)
3. [Quick start (Docker)](#quick-start-docker)
4. [Using NOVA AI](#using-nova-ai)
5. [Desktop app](#desktop-app)
6. [Browser extension](#browser-extension)
7. [Development without Docker](#development-without-docker)
8. [Tests and checks](#tests-and-checks)
9. [Putting it online](#putting-it-online)
10. [Configuration](#configuration)
11. [Troubleshooting](#troubleshooting)
12. [Project layout and docs](#project-layout-and-docs)

---

## Features

**Chat**
- Streaming answers (model `openai/gpt-oss-120b` on Groq) with Markdown, code highlighting and copy buttons.
- Chat history with search, rename, pin, archive, delete and a 30-day trash.
- Edit a message to branch the conversation, regenerate an answer, rate answers.
- Attach up to 3 screenshots or images per message (read by a Groq vision model), plus PDF, Word,
  Excel, PowerPoint, CSV, Markdown and text documents. Send an image on its own, with no text.
- Drag and drop files anywhere on the chat.
- Long-term memory you can see, edit and switch off; custom instructions.
- Tools: calculator, search in your files, optional web search, and optional Python code execution
  in an isolated sandbox.

**Quick Chat popup**
- Press **/** on any page of the website to open a small floating chat. Drag it anywhere, set its
  opacity from 100% down to 0%, and change any setting from inside it.
- Press **\\** to screenshot the whole screen straight into the popup. Nova leaves itself out of the shot.
- A history list to reopen any earlier chat. The controls only appear when you hover over the popup.

**Desktop app** (macOS, Windows, Linux)
- Runs in the background from the menu bar or tray, like the ChatGPT desktop app.
- **Option/Alt + /** opens Quick Chat from any app. **Option/Alt + \\** takes a screenshot into it.
  **Option/Alt + Shift + Q** fully quits Nova.
- Hidden from screenshots and screen sharing: `NSWindow.sharingType` on macOS,
  `SetWindowDisplayAffinity` on Windows.
- Asks for a passkey every time it starts, and locks permanently on that device after 3 wrong tries.

**Accounts and admin**
- Sign up and log in, with password reset by email and session management.
- Plans and billing through Razorpay (optional), and personal API keys.
- Data export and account deletion.
- An admin console with users, usage, health, models, moderation and audit logs.

---

## How it's built

```
Browser / desktop app ──► Next.js website (pages + /api proxy) ──► FastAPI backend ──► Groq API
                                                                  ├─ PostgreSQL 16 + pgvector
                                                                  ├─ Redis (streams, limits, queues)
                                                                  ├─ S3-compatible storage (RustFS locally)
                                                                  └─ background worker · code sandbox
```

| Part | Technology |
|---|---|
| Website | Next.js 16, React 19, TypeScript, Tailwind CSS, TanStack Query, Zustand |
| Backend | Python 3.12, FastAPI, SQLAlchemy (async), Alembic, ARQ workers |
| Data | PostgreSQL 16 + pgvector, Redis 7, S3 (RustFS locally) |
| AI | Groq only (official `groq` SDK) |
| Desktop | Electron 44, electron-builder |
| Tests | pytest, Vitest, Playwright (website, extension and desktop), k6 |
| Deploy | Docker Compose + Caddy on one server, or AWS with Terraform |

---

## Quick start (Docker)

This runs everything on your computer: the website, backend, worker, database, Redis, file storage
and a test inbox for emails.

### 1. Install the prerequisites

| Tool | Version | Get it |
|---|---|---|
| Git | any | https://git-scm.com |
| Docker Desktop (or Docker Engine + Compose v2) | recent | https://docs.docker.com/get-docker/ |
| make | any | built into macOS/Linux; on Windows use WSL 2 |

You also need a **Groq API key**. It's free to create at https://console.groq.com/keys, and you paste it into the app, not into a file.

> **Windows:** run all the commands below inside **WSL 2** (Ubuntu), with Docker Desktop's WSL
> integration turned on.

### 2. Download the code

```bash
git clone https://github.com/agnibhaproch-source/Nova-Ai.git
cd Nova-Ai
```

### 3. Create your settings file

```bash
cp .env.example .env
make secrets
```

`make secrets` prints three random values. Open `.env` in any editor and replace the three
`CHANGE_ME_generate_…` lines with them (`AUTH_SECRET`, `API_PROXY_SHARED_SECRET`,
`SANDBOX_RUNNER_TOKEN`). The `CHANGE_ME_dev_storage_…` values can stay as they are for local use.
Never commit `.env`.

### 4. Start it

```bash
make up
```

The first run builds the images and takes a few minutes. It also creates the database tables
automatically. Check that everything is up:

```bash
docker compose ps
```

### 5. Open it

| What | Address |
|---|---|
| NOVA AI website | http://localhost:3000 |
| Test inbox for password-reset emails (Mailpit) | http://localhost:8025 |
| File storage console (RustFS) | http://localhost:9001 |

Create an account at http://localhost:3000/signup, start a new chat, paste your Groq key into the
**"Paste your Groq API key"** box, and ask something.

**Make yourself admin (optional):** set `ADMIN_BOOTSTRAP_EMAIL=you@example.com` in `.env` *before*
signing up with that email. The first account with that address becomes an admin, and the console is at `/admin`.

### 6. Stop it

```bash
make down          # stop; your data is kept
make logs          # follow the logs while running
```

---

## Using NOVA AI

| Action | How |
|---|---|
| New chat | "New chat" in the sidebar, then paste your Groq key once for that chat |
| Open Quick Chat | Press **/** on any page (when you're not typing in a box) |
| Screenshot into Quick Chat | Press **\\**, or the camera button in the message box |
| Attach files | Paperclip button, paste, or drag and drop onto the chat |
| Send | Enter (Shift+Enter for a new line); a screenshot alone can be sent |
| Search chats | ⌘K / Ctrl+K |
| Stop an answer | Esc |
| Settings | Your name at the bottom left, then Settings (also in Quick Chat, via the gear icon) |

Each chat keeps its Groq key for 30 days after the last use (every message resets the timer). After that, Nova asks for it again.

---

## Desktop app

The desktop app shows the website's Quick Chat in its own floating window, so the website must be
running and reachable. That's `http://localhost:3000` from the Quick start, or your own domain.

### Run it from source (development)

```bash
pnpm install        # once, at the repo root (Node 22 + pnpm 9, see below)
make desktop
```

### Build an installer

1. **Choose the passkey.** The app asks for a passkey every time it starts. Set your own before
   building; the passkey itself is never stored, only a salted hash of it:

   ```bash
   cd apps/desktop && node scripts/set-passkey.js <your-passkey> && cd ../..
   ```

   Three wrong passkeys in a row lock the app on that device for good, so keep it safe.

2. **Build** with the address of your website baked in:

   ```bash
   make desktop-release url=https://nova.example.com       # macOS .dmg (universal)
   make desktop-release-all url=https://nova.example.com   # + Windows .exe and Linux .AppImage
   ```

   The installers go into `apps/desktop/dist/`, and are also copied to `apps/web/public/downloads/`.
   The website's **/download** page then offers them. They're large, so they're not stored in git.

   On macOS, `make desktop-release` first creates a local code-signing identity in
   `apps/desktop/.signing/`, which is git-ignored and never committed. It keeps macOS's Screen
   Recording permission from being asked for again after every update. For public distribution,
   sign with an Apple Developer ID (`CSC_LINK`/`CSC_NAME`) and notarize. On Windows, sign the
   `.exe` with a code-signing certificate.

### Install and first launch

- **macOS:** open `Nova-mac.dmg` and drag **Nova** into **Applications**. For unsigned builds,
  the first time, right-click Nova and choose **Open**. Enter the passkey. The first time you press
  **Option + \\**, macOS asks for **Screen Recording** permission: turn on Nova in System Settings
  → Privacy & Security → Screen Recording, then reopen Nova. This only happens once.
- **Windows:** run `Nova-win.exe`. If SmartScreen appears, choose **More info → Run anyway**. Use **Alt + /**.
- **Linux:** `chmod +x Nova-linux.AppImage && ./Nova-linux.AppImage`. Use **Alt + /**.

Nova keeps running in the background when you close its window. To fully quit, press **Option/Alt + Shift + Q** or use
**Quit Nova** in the menu-bar/tray icon. To change which website it connects to, use tray icon → **Settings…**.
More details: [`apps/desktop/README.md`](apps/desktop/README.md).

---

## Browser extension

A floating Quick Chat window for Chrome, Edge or Brave:

1. Open `chrome://extensions` and turn on **Developer mode**.
2. Click **Load unpacked** and choose the `apps/extension` folder.
3. Set the Nova address (default `http://localhost:3000`) on the options page that opens, and sign in to Nova in the same browser.
4. Press **Ctrl+Shift+1** (Mac: **⌘⇧1**) to open or hide it.

---

## Development without Docker

For working on the code with hot reload, run the data services in Docker and the apps directly.

**Prerequisites:** Node 22 (`.nvmrc`) with pnpm 9 (`corepack enable`), Python 3.12 with
[uv](https://docs.astral.sh/uv/), Docker, and make.

```bash
pnpm install                        # website, desktop app, tools
(cd apps/api && uv sync)            # backend
make infra                          # Postgres, Redis, S3 storage (RustFS), Mailpit in Docker
```

In `.env`, point the apps at `localhost` instead of the container names:

```ini
DATABASE_URL=postgresql+asyncpg://nova:nova@localhost:5432/nova
REDIS_URL=redis://localhost:6379/0
S3_ENDPOINT=http://localhost:9000
SMTP_HOST=localhost
API_INTERNAL_URL=http://localhost:8000
```

If those ports are taken on your machine, set `POSTGRES_HOST_PORT` or `REDIS_HOST_PORT` in `.env`, and use the same ports in the URLs above.

Then, in four terminals:

```bash
make migrate       # once, and after pulling new migrations
make dev-api       # FastAPI on :8000
make dev-worker    # background jobs
make dev-web       # website on :3000
```

**No Groq key yet?** `make stub` starts a local stand-in for Groq on port 8099. Set `GROQ_BASE_URL=http://localhost:8099` in `.env` for development. Never use this in production.

---

## Tests and checks

```bash
make check             # lint + type checks + backend, website and sandbox tests
make e2e               # Playwright end-to-end tests (website, Quick Chat, extension, desktop app)
make providers-check   # confirms Groq is the only AI provider in the code
make build && make bundle-check   # production build + confirm no secrets in browser code
make tf-validate       # validate the AWS Terraform (Docker; no AWS account needed)
make load s=chat_stream           # k6 load test against a stub-backed API
```

The end-to-end tests start their own isolated copy of the stack on ports 3100/8010, using a Groq stub,
so they never spend real Groq credit.

---

## Putting it online

**One server (simplest):** [`infra/deploy/README.md`](infra/deploy/README.md). Docker Compose with
Caddy for automatic HTTPS on a single Linux server (4 vCPU / 8 GB RAM), including backups, restore
and a GitHub Actions deploy workflow.

**AWS (scale-out):** [`infra/terraform/README.md`](infra/terraform/README.md) sets up WAF, a load
balancer, ECS Fargate, RDS PostgreSQL, ElastiCache Redis, S3, sandbox hosts and CloudWatch alarms.

Either way you'll need a domain, a real email service (SMTP) for password resets, and, to take payments, Razorpay keys.

---

## Configuration

All settings live in `.env` (see [`.env.example`](.env.example) for every option with comments,
and [`docs/42_ENVIRONMENT_VARIABLES.md`](docs/42_ENVIRONMENT_VARIABLES.md) for the full reference).
The most important ones:

| Setting | Meaning |
|---|---|
| `APP_URL` | Public address of the website |
| `AUTH_SECRET`, `API_PROXY_SHARED_SECRET`, `SANDBOX_RUNNER_TOKEN` | Random secrets (`make secrets`) |
| `GROQ_KEY_MODE` | `user` (default): each chat brings its own Groq key. `server`: one key for everyone in `GROQ_API_KEY` |
| `GROQ_DEFAULT_MODEL` | `openai/gpt-oss-120b` |
| `GROQ_USER_KEY_TTL_HOURS` | How long a chat keeps its key after the last use (default 720 = 30 days) |
| `SMTP_*` | Email for password resets (Mailpit locally) |
| `ADMIN_BOOTSTRAP_EMAIL` | The account with this email becomes admin on signup |
| `WEB_SEARCH_PROVIDER` | Turn on web search (SearXNG or Brave) |
| `RAZORPAY_*` | Payments (optional) |

Secrets belong only in `.env` / `.env.production` or your hosting's secret store. Never put them in
code, commits or `NEXT_PUBLIC_*` variables.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `make up` fails with "port is already allocated" | Another app uses 3000/5432/6379/9000. Stop it, or set `POSTGRES_HOST_PORT`/`REDIS_HOST_PORT` in `.env` |
| The website says to paste a Groq key | Normal for each new chat. Get a key at console.groq.com/keys |
| "Invalid Groq key" | Check the key starts with `gsk_` and is active in the Groq console |
| No password-reset email | Locally, emails go to Mailpit at http://localhost:8025, not your real inbox |
| Screenshots in the desktop app ask for permission again | Grant Screen Recording once, then reopen Nova. Builds made with `make desktop-release` keep the permission across updates |
| Desktop app shows a blank or "can't connect" window | The website isn't reachable. Start it, or set the right address in tray icon → Settings… |
| `make desktop` does nothing inside VS Code's terminal | Run `unset ELECTRON_RUN_AS_NODE` first |
| Desktop app says it's locked | 3 wrong passkeys were entered on that device. See [`apps/desktop/README.md`](apps/desktop/README.md) → Passkey |

---

## Project layout and docs

```
apps/
  api/             FastAPI backend, workers, migrations, tests
  web/             Next.js website, Quick Chat, end-to-end tests
  desktop/         Electron desktop app (passkey, shortcuts, capture exclusion)
  extension/       Chrome/Edge extension
  sandbox-runner/  Isolated code-execution service
docs/              Product and engineering documentation (the source of truth)
evals/             AI answer-quality evaluations
infra/             Docker images, single-server deploy, AWS Terraform, k6 load tests
scripts/           CI helpers (provider check, bundle secret scan)
```

The documentation in [`docs/`](docs/) describes every part of the system. Good places to start:
[`00_MASTER_INSTRUCTION.md`](docs/00_MASTER_INSTRUCTION.md) (index),
[`02_PRD.md`](docs/02_PRD.md) (product),
[`05_SYSTEM_ARCHITECTURE.md`](docs/05_SYSTEM_ARCHITECTURE.md),
[`44_LOCAL_DEVELOPMENT.md`](docs/44_LOCAL_DEVELOPMENT.md) and
[`53_IMPLEMENTATION_PHASES.md`](docs/53_IMPLEMENTATION_PHASES.md) (what's built).
Design decisions are recorded in [`docs/adr/`](docs/adr/).
