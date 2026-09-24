# Single-server deployment

Runs the whole stack on one Linux host with Docker: Caddy (automatic HTTPS) → web → API, plus the
worker, Postgres (pgvector), Redis and S3-compatible storage (RustFS). Good for launch and small/medium traffic; the AWS
reference architecture (docs/47 §1) is the scale-out path.

## One-time server setup
1. Ubuntu 24.04+, 4 vCPU / 8 GB RAM minimum. Install Docker Engine + compose plugin.
2. DNS: `A` records for `nova.example.com` and `files.nova.example.com` → the server. Open ports 80/443 only.
3. `sudo mkdir -p /opt/nova/infra/deploy && sudo chown $USER /opt/nova -R`
4. Copy `.env.production.example` → `/opt/nova/infra/deploy/.env.production`, fill it (`make secrets` for random values), `chmod 600`.
5. Optional code execution: install gVisor (`runsc`) and register it with Docker, then add `--profile tools`.
6. GitHub → Settings → Environments `staging`/`production` with secrets `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_DOMAIN`; require a reviewer for `production`.
7. Backups: `crontab -e` → `30 2 * * * /opt/nova/infra/deploy/backup.sh` and ship `/var/backups/nova` off-host.

## Deploy
Push a tag `v1.2.3` (or run the **deploy** workflow). It builds and pushes the four images to GHCR, copies
the compose files, sets `IMAGE_TAG`, pulls, runs migrations (the `migrate` one-off runs before the API
starts), restarts, and smoke-tests `https://<domain>/api/v1/app-config`.

## Rollback
Set `IMAGE_TAG` in `.env.production` to the previous `sha-…` tag and `docker compose … up -d`.
Migrations are expand/contract, so the previous release runs against the newer schema.

## Try it locally
```bash
docker build --target prod -t nova/nova-api:dev apps/api
docker build --target prod -f apps/web/Dockerfile -t nova/nova-web:dev .
cp infra/deploy/.env.production.example infra/deploy/.env.production   # fill secrets
# in it: DOMAIN=localhost CADDY_TLS=internal HTTP_PORT=8080 HTTPS_PORT=8443 PUBLIC_PORT_SUFFIX=:8443 REGISTRY=nova IMAGE_TAG=dev
docker compose -f infra/deploy/docker-compose.prod.yml --env-file infra/deploy/.env.production up -d
curl -k https://localhost:8443/api/v1/app-config
```
