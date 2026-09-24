# Worker heartbeat / queue backlog / stale generations / purge overdue

**Check:** Admin → Health → `worker.last_heartbeat`, `queue.depth`, `files_stuck`. Worker logs for
`job.failed`.

**Fix**
- No heartbeat → restart the worker service; if it crash-loops, the last `job.failed` names the job.
- Backlog → scale worker replicas; `requeue_stuck_files` cron recovers files stuck > 15 min automatically.
- Stale generations (reaper marking many `interrupted`) → API instances are being killed mid-stream; check deploy draining and OOM kills.
- Purge overdue → run the purge job manually for the user id (`purge_user`) and investigate its error.

**Verify:** heartbeat < 60 s old, queue depth falling, no new `job.failed`.
