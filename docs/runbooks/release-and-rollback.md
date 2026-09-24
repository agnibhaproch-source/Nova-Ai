# Release and rollback

**Release:** CI green on `main` → build images (api, web, sandbox-runner, sandbox-python) tagged with the
git sha → run `alembic upgrade head` as a one-off task → roll API/worker/runner to the new digest →
smoke: `/readyz`, sign in, send a message on a test chat, upload a small file.

Migrations must be backward compatible with the previous release (expand → deploy → contract), so a
rollback never needs a down-migration.

**Rollback:** re-point services to the previous image digest (keep the last 5). Don't run `alembic downgrade`
in production; ship a forward fix instead.

**Verify:** error rate back to baseline for 15 min; smoke passes.
