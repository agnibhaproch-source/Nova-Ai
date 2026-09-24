# Database unhealthy

**Check:** readiness `database` check; CPU, connections, replication lag; `pg_stat_activity` for long
transactions (`state='idle in transaction'` > 1 min) and lock waits.

**Fix**
- Connections exhausted → reduce API/worker replicas temporarily; kill idle-in-transaction sessions (`pg_terminate_backend`).
- Slow queries → `pg_stat_statements` top by total time; add the missing index in a migration (never ad hoc in prod).
- Disk > 85% → purge jobs running? (`worker-and-queues.md`); grow storage.
- Primary lost → promote replica (managed failover), update `DATABASE_URL` if the endpoint changed, restart API/worker.

**Verify:** `/readyz` green, p95 query latency normal, no lock waits.
