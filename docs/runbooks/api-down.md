# API down / high 5xx

**Means:** synthetic checks fail, or 5xx > 2% for 5 min.

**Check**
1. `GET /readyz` on each API instance → which dependency is failing (`database`, `redis`, `migrations`, `models`).
2. Admin → **Health** (`GET /api/v1/admin/health`) and **Errors** (`/admin/errors`) for the top error codes.
3. Logs: filter `level=error`, group by `event` and `request_id`. A spike in one `event` usually names the cause.
4. Did a deploy just happen? Compare the error start time with the release (`release-and-rollback.md`).

**Fix**
- `migrations` not ready → a release shipped without `alembic upgrade head`; run the migration task.
- `models` not ready → `config/models.yaml` invalid for this env (see `groq-failures.md`).
- Dependency down → follow `database.md` / `redis.md`.
- Bad release → roll back (`release-and-rollback.md`).

**Verify:** `/readyz` 200 on all instances; 5xx < 0.5% for 15 min; synthetic check green.
