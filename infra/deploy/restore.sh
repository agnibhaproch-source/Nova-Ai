#!/usr/bin/env bash
# Restore a backup into a (fresh) stack: ./restore.sh /var/backups/nova/nova-<stamp>.dump
# Stops the app, restores Postgres and objects, then starts everything (docs/runbooks/restore-from-backup.md).
set -euo pipefail
cd "$(dirname "$0")"
DUMP=${1:?usage: restore.sh <dump file>}
FILES=$(dirname "$DUMP")/files
C="docker compose -f docker-compose.prod.yml --env-file .env.production"
env_get() { grep -E "^$1=" .env.production | tail -1 | cut -d= -f2-; }
export S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET
S3_ACCESS_KEY=$(env_get S3_ACCESS_KEY); S3_SECRET_KEY=$(env_get S3_SECRET_KEY); S3_BUCKET=$(env_get S3_BUCKET)
$C stop web api worker >/dev/null 2>&1 || true
$C up -d --wait postgres redis storage
$C up storage-init >/dev/null
$C exec -T postgres pg_restore -U nova -d nova --clean --if-exists --no-owner < "$DUMP"
if [ -d "$FILES" ]; then
  docker run --rm --network nova-prod_default -v "$FILES:/backup:ro" \
    -e AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" -e AWS_DEFAULT_REGION=us-east-1 \
    amazon/aws-cli:2.37.2 --endpoint-url http://storage:9000 s3 sync --only-show-errors /backup "s3://$S3_BUCKET"
fi
$C up -d
echo "restore ok from $DUMP"
