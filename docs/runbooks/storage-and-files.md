# Storage errors / files stuck

**Check:** S3 / RustFS status; Admin → Errors → `files` (e.g. `SCAN_UNAVAILABLE`, `EXTRACTION_FAILED`);
Admin → Health → `storage`, `files_stuck`.

**Fix**
- S3 errors → credentials/permissions changed? Bucket policy? Region outage? Restore access; uploads resume.
- `SCAN_UNAVAILABLE` → ClamAV down: restart it; the job retries with backoff and never marks files ready unscanned.
- Files stuck → the `requeue_stuck_files` cron re-enqueues after 15 min; users can also press Retry.

**Verify:** a test upload reaches `ready`; `files_stuck` = 0.
