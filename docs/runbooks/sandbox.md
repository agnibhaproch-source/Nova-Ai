# Sandbox runner

**Check:** `GET <runner>/healthz` (Docker reachable + image present); orphan removals in runner logs.

**Fix**
- Unhealthy → Docker daemon down or image missing: `docker build -t nova-sandbox-python:<ver> infra/docker/sandbox-python` (or pull), restart runner.
- Many orphans → executions are outliving limits; check host load; the reaper removes containers older than 60 s.
- Suspected escape/abuse → set Admin → Settings `disabled_tools` to include `code_execution` (instant kill switch), then follow `security-incident.md`.

**Verify:** health OK; a `print(1+1)` run returns `2` in < 3 s.
