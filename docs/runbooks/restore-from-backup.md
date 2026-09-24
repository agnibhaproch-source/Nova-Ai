# Restore from backup (docs/50)

1. Pick the recovery point (PITR timestamp just before the damage).
2. Restore Postgres to a **new** instance at that time (managed PITR). Never overwrite the live DB first.
3. Point a staging API at it; run `alembic current` (schema matches the release?) and spot-check users, conversations, files.
4. Switch `DATABASE_URL` for API + worker to the restored instance during a maintenance window (banner via Admin → Settings).
5. Object storage: S3 versioning restores deleted/overwritten objects (`users/{uid}/…`); lifecycle rules keep versions 30 days.
6. Redis is rebuilt from scratch (sessions re-cache from Postgres; users re-enter BYOK chat keys).

**DR drill:** do steps 1–3 quarterly into an isolated environment and record time-to-restore.

## Single-server stack (infra/deploy)

```bash
BACKUP_DIR=/var/backups/nova ./backup.sh                 # pg_dump + object mirror
./restore.sh /var/backups/nova/nova-<stamp>.dump         # stops app, restores DB + objects, restarts
```

## Drill log

| Date | Environment | Scenario | Result | Time to restore |
|---|---|---|---|---|
| 2026-09-24 | single-server stack, production mode (local) | Seeded account + memory + uploaded file → `backup.sh` → `docker compose down -v` (all volumes destroyed; verified 0 users) → fresh stack → `restore.sh` | Login works, memory present, file downloads byte-identical | 46 s (incl. fresh stack boot) |

Finding during the drill: Caddy rewrote the `Host` header for `files.<domain>`, which broke every
presigned **download** (SigV4 signs the host). Fixed in `infra/deploy/Caddyfile`; uploads (POST
policy) were unaffected.
