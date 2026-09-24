# 50 — Backup & Recovery

## 1. Objectives

| Data | RPO | RTO |
|---|---|---|
| PostgreSQL (primary system of record) | ≤ 5 minutes | ≤ 1 hour |
| S3 objects (uploads, exports) | ≤ 24 hours for deletions/overwrites (versioning makes it ~0 for accidental deletes within retention) | ≤ 4 hours |
| Redis | Not backed up (ephemeral by design) | Rebuild ≤ 15 minutes |
| Configuration & secrets | Versioned (git, Secrets Manager versions) | ≤ 1 hour |
| Full region disaster | ≤ 1 hour (cross-region snapshot copies) | ≤ 8 hours |

## 2. Database backups

- **Continuous:** RDS automated backups with point-in-time recovery (PITR), retention **35 days** (transaction logs every 5 min → RPO ≤ 5 min).
- **Daily snapshots:** automated; plus **weekly manual snapshots** retained 90 days and **monthly** retained 1 year (AWS Backup plan `nova-db`), encrypted with KMS.
- **Cross-region:** AWS Backup copies daily snapshots to `ap-southeast-1` (Singapore), retained 14 days.
- **Logical backup:** weekly `pg_dump --format=custom` of schema + data to a separate, locked-down S3 bucket (`nova-backups-logical`, Object Lock governance 35 days) for tooling independence.
- Deleted-user data remains in backups until they age out (≤ 35 days for PITR/daily, 90 days weekly, 1 year monthly). **Privacy requirement:** monthly snapshots are restored only into isolated environments, and on restore the `purge_deleted_users` replay procedure (§7) must run before any use. The privacy policy states backup retention.

## 3. Object storage backups

- S3 **versioning** enabled; lifecycle: noncurrent versions expire after 30 days; incomplete multipart uploads aborted after 1 day; `users/*/exports/` current versions expire after 2 days.
- **Cross-region replication** (CRR) for `users/*/files/*` to the DR region bucket (Phase 11), replicating delete markers **off** to protect against accidental deletes, while `purge_*` jobs explicitly delete replicated objects too (a replication-aware purge deletes in both buckets).
- MinIO (dev) has no backups.

## 4. Retention summary

| Artifact | Retention |
|---|---|
| RDS PITR | 35 days |
| Weekly snapshots | 90 days |
| Monthly snapshots | 365 days |
| Logical dumps | 35 days (object lock) |
| S3 noncurrent versions | 30 days |
| Application logs | 30 days hot, 90 days archive |
| Audit logs (DB) | 2 years (then archived to S3 Glacier as CSV, 5 years) |

## 5. Restore procedures

### 5.1 Point-in-time restore (logical corruption, bad migration, accidental mass delete)
1. Declare incident; freeze writes if corruption is spreading (`system_settings.chat_enabled=false`, scale workers to 0).
2. `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier nova-prod --target-db-instance-identifier nova-prod-pitr-<ts> --restore-time <T-before-incident>`.
3. Validate on the restored instance: row counts, `alembic current`, spot-check affected tables (runbook queries).
4. Choose: (a) **swap** — update `DATABASE_URL` secret to the restored endpoint and redeploy (full rollback to T, losing writes after T), or (b) **surgical repair** — copy affected rows from the restored instance into production via `pg_dump -t`/`INSERT ... SELECT` over `dblink`/`postgres_fdw`.
5. Re-enable features; post-mortem.

### 5.2 Instance loss
Multi-AZ failover handles AZ/instance failures automatically (RTO minutes).

### 5.3 S3 object recovery
Restore a previous version (`aws s3api copy-object --copy-source bucket/key?versionId=…`) or from the replica bucket. Runbook script `scripts/restore_s3_prefix.py --prefix users/<id>/ --at <timestamp>`.

### 5.4 Redis loss
Provision a new cluster/fail over; the app recovers: counters rebuilt lazily, `requeue_stuck_files` re-enqueues processing, active generations are reaped and retryable.

## 6. Disaster recovery (region loss)

1. Restore latest cross-region snapshot in DR region (`ap-southeast-1`) as a new RDS instance (Multi-AZ).
2. Deploy infra via Terraform with `region=ap-southeast-1` workspace (ECS services, ElastiCache, TEI, sandbox ASG).
3. Point the app to the replica S3 bucket (`S3_BUCKET`, `S3_REGION`).
4. Update Vercel `API_INTERNAL_URL` to the DR ALB; DNS TTLs 60 s.
5. Verify with smoke tests; communicate status.
Target RTO ≤ 8 h, RPO ≤ 1 h (snapshot copies hourly in Phase 11; daily before that → document actual RPO in the status table of the runbook).

## 7. Restore testing

- **Monthly:** automated job restores the latest daily snapshot into an isolated `nova-restore-test` instance, runs `alembic current`, integrity queries (FK consistency checks, counts vs. production metrics within tolerance), then runs the deleted-user purge replay (`scripts/replay_purges.py` deletes users whose ids appear in `audit_logs` action `user.deleted` after the snapshot time — reading from the production audit log), then destroys the instance. Results posted to `#nova-ops`.
- **Quarterly:** full DR game day (region restore in staging account) measuring actual RTO/RPO.
- **After each schema-major release:** PITR restore rehearsal in staging.

## 8. Responsibilities

Platform on-call owns backup monitoring (AWS Backup job failure alerts → P2) and restore drills; the engineering lead approves any production restore swap.
