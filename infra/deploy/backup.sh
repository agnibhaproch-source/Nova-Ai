#!/usr/bin/env bash
# Nightly backup: Postgres (pg_dump custom format) + object storage mirror (docs/50).
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
  -e S3_ACCESS_KEY -e S3_SECRET_KEY -e S3_BUCKET --entrypoint /bin/sh quay.io/minio/mc:latest -c \
  'mc alias set local http://minio:9000 "$S3_ACCESS_KEY" "$S3_SECRET_KEY" >/dev/null && mc mirror --quiet --overwrite "local/$S3_BUCKET" /backup'
find "$DEST" -maxdepth 1 -name 'nova-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "backup ok: $DEST/nova-$STAMP.dump (+ files/)"
