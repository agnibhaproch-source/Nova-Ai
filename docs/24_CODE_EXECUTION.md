# 24 — Code Execution Sandbox

## 1. Hard rules

- **User/model-generated code must never execute inside the FastAPI process, the worker process, or any container that holds application secrets or network access to internal services.** No `exec`, `eval`, `subprocess` of user code anywhere in `apps/api`.
- Execution happens only in ephemeral containers created by `apps/sandbox-runner`, running on hosts dedicated to sandboxing.
- v1 language: **Python 3.12** only.

## 2. Architecture

```
api/worker (ToolEngine → CodeExecutionTool → SandboxClient)
     │ HTTPS/HTTP on private network, Authorization: Bearer SANDBOX_RUNNER_TOKEN
     ▼
sandbox-runner (FastAPI, on isolated sandbox host/VM; no secrets except its own token)
     │ Docker Engine API (local unix socket, on the sandbox host only)
     ▼
ephemeral container from image nova-sandbox-python:<version>
   runtime: runsc (gVisor)   network: none   rootfs: read-only
```

In local development, `sandbox-runner` runs in Docker Compose with the Docker socket mounted and `SANDBOX_RUNTIME=runc` (gVisor optional on Linux). **This mode is refused when `APP_ENV` is `staging` or `production`** (runner startup check: runtime must be `runsc`).

## 3. Sandbox image (`infra/docker/sandbox-python/Dockerfile`)

- Base: `python:3.12-slim` pinned by digest.
- Preinstalled packages (pinned): `numpy`, `pandas`, `scipy`, `sympy`, `matplotlib` (Agg backend), `python-dateutil`, `tabulate`. No `pip` at runtime (pip removed; `PIP_NO_INDEX=1`).
- User `sandbox` uid/gid 65534; `WORKDIR /work`; no setuid binaries (`find / -perm /6000 -exec chmod a-s {} +`).
- `ENTRYPOINT ["python", "-I", "-B", "/opt/runner/run.py"]` — a tiny harness that reads ONE JSON line from stdin (`{code, timeout_seconds, files}`), writes `/work/main.py` and `/work/input/*`, runs the code with `runpy.run_path` under `SIGALRM`, redirects fd 1/2 to capped files, captures matplotlib figures via a `plt.show()` shim (max 3 images, 1 MB each), and prints ONE JSON result line to the real stdout. Code cannot be copied in with `put_archive` because Docker refuses archive writes on a read-only rootfs, and the tmpfs vanishes when the container exits.

## 4. Container limits (per execution)

| Control | Setting |
|---|---|
| Runtime | `runsc` (gVisor) |
| Network | `NetworkMode: none` |
| Root filesystem | `ReadonlyRootfs: true` |
| Writable space | `Tmpfs: {"/work": "rw,size=64m,uid=65534,gid=65534,mode=0700,noexec", "/tmp": "rw,size=16m,noexec"}` (the harness writes `/work/main.py` from stdin; python runs it by path so `noexec` is fine) |
| User | `65534:65534` |
| Capabilities | `CapDrop: ["ALL"]` |
| Privileges | `SecurityOpt: ["no-new-privileges:true"]` + default seccomp (gVisor adds its own sandboxing) |
| Memory | `Memory: 256 MiB`, `MemorySwap: 256 MiB` (no swap) |
| CPU | `NanoCpus: 500_000_000` (0.5 CPU) |
| PIDs | `PidsLimit: 64` |
| Ulimits | `nofile 256`, `fsize 16 MiB`, `nproc 64` |
| Wall timeout | 10 s default, 20 s for `pro` plan |
| Output | stdout + stderr capped at 64 KB each (truncated with marker) |
| Env | only `PYTHONUNBUFFERED=1`, `MPLBACKEND=Agg`, `HOME=/work` |
| Mounts | none (no host paths, no docker socket) |
| Labels | `nova.sandbox=1`, `nova.execution_id=<id>`, `nova.expires_at=<epoch>` |

## 5. Runner API

`POST /v1/execute`

```json
{"execution_id":"uuid","language":"python","code":"print(1+1)","timeout_seconds":10,
 "files":[{"name":"data.csv","content_b64":"..."}]}
```
- `files` (optional): user files the model referenced by id — the **API** resolves ownership and passes content (≤ 5 files, ≤ 10 MB total) which are placed in `/work/input/` (read-only copy). v1 enables this only for CSV/XLSX/TXT attached to the conversation.

Response `200`:
```json
{"execution_id":"uuid","exit_code":0,"stdout":"2\n","stderr":"","timed_out":false,"truncated":false,
 "duration_ms":412,"images":[{"name":"figure1.png","content_b64":"..."}],"oom_killed":false}
```

Errors: `401` bad token; `429` runner at capacity (`SANDBOX_BUSY`); `503` Docker unavailable.

`DELETE /v1/executions/{execution_id}` → kills and removes the container (cancellation).
`GET /healthz` → runner + Docker reachable + image present.

## 6. Execution lifecycle

1. Acquire concurrency slot (`asyncio.Semaphore(SANDBOX_MAX_CONCURRENCY)`, default 8 per runner); none within 2 s → `429 SANDBOX_BUSY`.
2. Create container (limits §4, `stdin_open`), attach stdin, start, send the payload line.
3. The harness enforces `timeout_seconds` itself (`SIGALRM`, exit 124, `timed_out=true`); the runner `wait`s `timeout_seconds + 2` and SIGKILLs on overrun (hard timeout).
4. Parse the harness's final JSON line from stdout (stdout/stderr already capped, images base64).
5. If there is no result line (OOM kill, hard timeout, crash), fall back to the container state and capped stderr.
6. `inspect` for `OOMKilled`, exit code.
7. **Always** remove container (`force=True`) in `finally`.
8. Orphan reaper loop (every 30 s): remove containers with label `nova.sandbox=1` older than `expires_at` (start + 60 s).

## 7. API side (`CodeExecutionTool`)

- Validate code length ≤ 20,000 chars; language `python`.
- `SandboxClient.execute()` via `httpx.AsyncClient(base_url=SANDBOX_RUNNER_URL, timeout=timeout+10)`, bearer token; retry once on `SANDBOX_BUSY` after 1 s.
- Images returned are stored as files (`kind='image'`, `purpose='attachment'`, `users/{uid}/files/{file_id}`) with status `ready` and linked into the `code` part `data.images: [file_id]` for display.
- `model_content`: `{"tool":"code_execution","untrusted_content":true,"exit_code":0,"stdout":"...","stderr":"...","timed_out":false,"images":["figure1.png"]}` (stdout/stderr fitted to budget, tail-preferred).
- UI `code` part: syntax-highlighted source, collapsible stdout/stderr panes, exit badge, duration, images inline.

## 8. Network restrictions

- Containers: no network namespace interfaces except loopback.
- sandbox-runner host: inbound only from API/worker subnets on the runner port; outbound blocked except to the container registry (image pulls during deploy) and observability endpoints.
- The runner holds **no** application secrets (no DB, Redis, S3, Groq credentials).

## 9. Process restrictions and abuse prevention

- PID limit prevents fork bombs; memory limit prevents RAM exhaustion; tmpfs sizes bound disk writes; output caps bound log volume.
- Crypto-mining and long loops bounded by CPU share and wall timeout.
- Per-user quotas (`code_executions_per_day`) and rate limit (5/min).
- Repeated OOM/timeouts (> 20/hour for a user) create a `moderation_flags(source='automated', category='rate_abuse')`.

## 10. Cleanup

- Container removed after each execution (step 7) and by the orphan reaper.
- Nothing persists between executions (fresh container every time; no reuse or warm pools in v1).
- Warm pool optimization (Phase 11, optional): pre-created **unstarted** containers with the same limits, each used once and destroyed.

## 11. Testing

- Runner unit tests with a fake Docker client; integration tests in CI on Linux with `runc` (gVisor tests in a nightly job on a runner with gVisor installed).
- Security tests (must fail safely): network access (`socket.create_connection(("1.1.1.1",53))` → error), writing outside `/work` and `/tmp` → error, fork bomb → contained, `while True: pass` → timeout, 1 GB allocation → OOM, reading `/proc/1/environ` → contains no secrets, output flood → truncated.
