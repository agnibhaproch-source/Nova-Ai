#!/usr/bin/env bash
# Builds a throwaway .env for CI from .env.example: random secrets, host-side endpoints.
set -euo pipefail
cd "$(dirname "$0")/.."
rand() { python3 -c "import secrets;print(secrets.token_urlsafe(48))"; }
sed \
  -e "s#^API_PROXY_SHARED_SECRET=.*#API_PROXY_SHARED_SECRET=$(rand)#" \
  -e "s#^AUTH_SECRET=.*#AUTH_SECRET=$(rand)#" \
  -e "s#^SANDBOX_RUNNER_TOKEN=.*#SANDBOX_RUNNER_TOKEN=$(rand)#" \
  -e "s#^DATABASE_URL=.*#DATABASE_URL=postgresql+asyncpg://nova:nova@localhost:5432/nova#" \
  -e "s#^REDIS_URL=.*#REDIS_URL=redis://localhost:6379/0#" \
  -e "s#^S3_ENDPOINT=.*#S3_ENDPOINT=http://localhost:9000#" \
  -e "s#^S3_ACCESS_KEY=.*#S3_ACCESS_KEY=novaci#" \
  -e "s#^S3_SECRET_KEY=.*#S3_SECRET_KEY=$(python3 -c 'import secrets;print(secrets.token_hex(16))')#" \
  -e "s#^EMBEDDING_DIMENSIONS=.*#EMBEDDING_DIMENSIONS=384#" \
  -e "s#^SMTP_HOST=.*#SMTP_HOST=localhost#" \
  -e "s#^SMTP_PORT=.*#SMTP_PORT=1025#" \
  .env.example > .env
ln -sf ../../.env apps/web/.env
echo "ci_env: wrote .env"
