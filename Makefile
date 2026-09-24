# NOVA AI developer entrypoints (docs/44_LOCAL_DEVELOPMENT.md)
SHELL := /bin/bash
API := apps/api
WEB := apps/web

.PHONY: infra up down logs migrate revision migrate-check seed secrets dev-api dev-worker dev-web \
        stub up-tools sandbox-image bundle-check e2e test-runner load evals desktop desktop-dist desktop-release desktop-release-all tf-validate lint format typecheck test test-api test-web check build providers-check

infra:            ## postgres, redis, S3 storage (RustFS), mailpit
	docker compose up -d postgres redis storage storage-init mailpit

up:               ## full stack in containers
	docker compose --profile app up -d --build

up-tools:         ## + sandbox-runner, searxng
	docker compose --profile app --profile tools up -d --build

sandbox-image:    ## image used for user code containers
	docker build -t nova-sandbox-python:dev infra/docker/sandbox-python

down:
	docker compose --profile app --profile tools --profile embeddings --profile security down

logs:
	docker compose logs -f $(s)

migrate:
	cd $(API) && uv run alembic upgrade head

revision:
	cd $(API) && uv run alembic revision --autogenerate -m "$(m)"

migrate-check:
	cd $(API) && uv run alembic check

secrets:          ## print random secrets for .env
	@python3 -c "import secrets;[print(f'{k}={secrets.token_urlsafe(48)}') for k in ('AUTH_SECRET','API_PROXY_SHARED_SECRET','SANDBOX_RUNNER_TOKEN')]"

dev-api:
	cd $(API) && uv run uvicorn app.main:app --reload --port 8000

dev-worker:
	cd $(API) && uv run arq app.workers.settings.WorkerSettings --watch app

dev-web:
	cd $(WEB) && pnpm dev

stub:             ## local Groq stub for development without a key (never in staging/prod)
	cd $(API) && uv run uvicorn tests.fakes.groq_stub_server:app --port 8099

lint:
	cd $(API) && uv run ruff check . && uv run ruff format --check .
	cd $(WEB) && pnpm exec eslint src

format:
	cd $(API) && uv run ruff format . && uv run ruff check . --fix

typecheck:
	cd $(API) && uv run mypy app
	cd $(WEB) && pnpm typecheck

test-api:
	cd $(API) && uv run pytest -q $(if $(k),-k "$(k)",)

test-web:
	cd $(WEB) && pnpm exec vitest run

test: test-api test-web test-runner

check: lint typecheck test

build:
	cd $(WEB) && pnpm build

providers-check:  ## Groq is the only LLM provider (docs/00 R1)
	./scripts/check_forbidden_providers.sh

bundle-check:     ## no secrets in client bundles (run after `make build`)
	./scripts/check_bundle_secrets.sh

e2e:              ## Playwright against the Groq stub (stops nothing; uses ports 3000/8000/8099)
	cd $(WEB) && pnpm exec playwright test

test-runner:
	cd apps/sandbox-runner && uv run pytest -q

load:             ## k6 against a stub-backed API: make load s=chat_stream (needs infra/k6/users.json)
	docker run --rm -v "$(CURDIR)/infra/k6:/k6" -w /k6 -e PROXY_SECRET="$$(grep ^API_PROXY_SHARED_SECRET .env | cut -d= -f2-)" \
	  -e API_URL=$${API_URL:-http://host.docker.internal:8010/api/v1} grafana/k6 run $(or $(s),chat_stream).js

desktop:          ## run the Nova desktop app (Quick Chat on Alt+/ and Alt+\)
	cd apps/desktop && env -u ELECTRON_RUN_AS_NODE pnpm start

desktop-dist:     ## build the desktop installer for this OS into apps/desktop/dist
	cd apps/desktop && env -u ELECTRON_RUN_AS_NODE pnpm dist

desktop-release:  ## build Nova-mac.dmg for $(url) and publish it on the website's /download page
	cd apps/desktop && ( [ -n "$$CSC_LINK$$CSC_NAME" ] || scripts/signing-identity.sh ) && rm -rf dist && env -u ELECTRON_RUN_AS_NODE CSC_IDENTITY_AUTO_DISCOVERY=$${CSC_IDENTITY_AUTO_DISCOVERY:-false} \
	  pnpm exec electron-builder --mac -c.extraMetadata.novaUrl=$(or $(url),$$(grep ^APP_URL ../../.env | cut -d= -f2-))
	mkdir -p apps/web/public/downloads && cp apps/desktop/dist/Nova-mac.dmg apps/web/public/downloads/Nova-mac.dmg

desktop-release-all: desktop-release  ## + Windows installer and Linux AppImage on /download
	cd apps/desktop && env -u ELECTRON_RUN_AS_NODE pnpm exec electron-builder --win nsis --x64 --linux AppImage --x64 \
	  -c.extraMetadata.novaUrl=$(or $(url),$$(grep ^APP_URL ../../.env | cut -d= -f2-))
	cp apps/desktop/dist/Nova-win.exe apps/desktop/dist/Nova-linux.AppImage apps/web/public/downloads/

evals:            ## NOVA_API_KEY + EVAL_GROQ_API_KEY required: make evals suite=general_qa
	cd evals && uv run python -m nova_evals.runner --suite $(or $(suite),general_qa) --baseline

tf-validate:  ## fmt-check + validate the AWS Terraform (docker; no credentials needed)
	docker run --rm -v $(CURDIR)/infra/terraform:/tf -w /tf hashicorp/terraform:1.16 fmt -recursive -check
	docker run --rm -v $(CURDIR)/infra/terraform:/tf -w /tf/envs/production --entrypoint sh hashicorp/terraform:1.16 \
	  -c "terraform init -backend=false -input=false >/dev/null && terraform validate && rm -rf .terraform"
