# Runbooks

One page per alert (docs/39 §5) plus incident and setup procedures. Each page: **what it means →
check → fix → verify**. Admin API calls go through the web origin with an admin session, or
directly to FastAPI with `X-Nova-Proxy-Secret` from a trusted host.

| Runbook | Alerts / use |
|---|---|
| [api-down.md](api-down.md) | API down, High 5xx, Error budget burn |
| [groq-failures.md](groq-failures.md) | Groq failures, Groq auth error, TTFT degraded, SSE failures, Cost |
| [database.md](database.md) | DB unhealthy |
| [redis.md](redis.md) | Redis unhealthy, Rate-limit fallback active |
| [worker-and-queues.md](worker-and-queues.md) | Worker heartbeat, Queue backlog, Stale generations, Account purge overdue |
| [storage-and-files.md](storage-and-files.md) | Storage errors, files stuck |
| [sandbox.md](sandbox.md) | Sandbox |
| [billing-webhooks.md](billing-webhooks.md) | Webhook failures; creating Razorpay plans |
| [security-incident.md](security-incident.md) | Suspected breach, leaked key, abuse |
| [restore-from-backup.md](restore-from-backup.md) | Data loss, DR drill (docs/50) |
| [release-and-rollback.md](release-and-rollback.md) | Deploys, bad release |
