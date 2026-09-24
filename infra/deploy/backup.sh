#!/usr/bin/env bash
# Nightly backup: Postgres (pg_dump custom format) + a copy of the file storage bucket (docs/50).
# Cron: 30 2 * * * /opt/nova/infra/deploy/backup.sh   — then ship $BACKUP_DIR off the host.
set -euo pipefail
cd "$(dirname "$0")"
DEST=${BACKUP_DIR:-/var/backups/nova}
KEEP_DAYS=${KEEP_DAYS:-14}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
C="docker compose -f docker-compose.prod.yml --env-file .env.production"
env_get() { grep -E "^$1=" .env.production | tail -1 | cut -d= -f2-; }
export S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET
S3_ACCESS_KEY=$(env_get S3_ACCESS_KEY); S3_SECRET_KEY=$(env_get S3_SECRET_KEY); S3_BUCKET=$(env_get S3_BUCKET)
mkdir -p "$DEST/files"
$C exec -T postgres pg_dump -U nova -d nova --format=custom > "$DEST/nova-$STAMP.dump.tmp"
mv "$DEST/nova-$STAMP.dump.tmp" "$DEST/nova-$STAMP.dump"
docker run --rm --network nova-prod_default -v "$DEST/files:/backup" \
  -e AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" -e AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" -e AWS_DEFAULT_REGION=us-east-1 \
  amazon/aws-cli:2.37.2 --endpoint-url http://storage:9000 s3 sync --only-show-errors "s3://$S3_BUCKET" /backup
find "$DEST" -maxdepth 1 -name 'nova-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "backup ok: $DEST/nova-$STAMP.dump (+ files/)"
