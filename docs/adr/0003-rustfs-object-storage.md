# ADR 0003 — RustFS replaces MinIO for local and single-server object storage

- Status: accepted
- Date: 2026-09-25
- Supersedes: MinIO (`quay.io/minio/minio`, `quay.io/minio/mc`) in `docker-compose.yml`, `infra/deploy/` and CI

## Context
MinIO stopped publishing its community container images. Every tag (including pinned releases) on
Docker Hub and quay.io became unpullable, so CI (`ci / backend`) failed at `docker compose up`, and a
fresh clone could not start. Only machines with a cached image still worked.

Nova needs from S3-compatible storage: presigned POST uploads with `content-length-range`,
presigned GET, private buckets, bucket CORS for browser uploads, and versioning (single-server
production). AWS deployments use real S3 and are unaffected.

## Decision
- Use RustFS (`rustfs/rustfs:1.0.0`, Apache-2.0, S3-compatible) as the `storage` service.
- Prepare buckets with the official AWS CLI image (`amazon/aws-cli:2.37.2`) running
  `infra/deploy/storage-init.sh`: create bucket, CORS limited to the app's origin(s), versioning in
  production. Backups/restores use `aws s3 sync` instead of `mc mirror`.
- Pin both image versions (a floating `latest` is how the outage went unnoticed).

## Verification
Against RustFS: presigned POST accepted within the size limit (204) and rejected above it
(400 `EntityTooLarge`), presigned GET 200, anonymous GET 403, versioning enabled, CORS allows the
app origin and refuses others (403). Full backend and E2E suites pass (uploads, screenshots, drag
and drop); the production stack serves uploads/downloads through Caddy at `files.<domain>`.

## Consequences
- CORS is now explicit per bucket (MinIO allowed all origins by default), which is stricter.
- Existing local MinIO data is not migrated automatically; copy it with `aws s3 sync` (the old
  `*_miniodata` volume is left untouched).
