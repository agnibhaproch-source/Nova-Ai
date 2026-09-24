"""Docker Engine calls for one execution: create → put code → start → wait → collect → remove."""

from __future__ import annotations

import base64
import contextlib
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import docker
from docker.types import Ulimit

from sandbox_runner import limits
from sandbox_runner.config import Settings


@dataclass
class InputFile:
    name: str
    content: bytes


@dataclass
class Result:
    execution_id: str
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool
    duration_ms: int
    oom_killed: bool
    images: list[dict[str, str]] = field(default_factory=list)


def _cap(data: bytes) -> tuple[str, bool]:
    if len(data) <= limits.OUTPUT_CAP:
        return data.decode(errors="replace"), False
    head = data[: limits.OUTPUT_CAP].decode(errors="replace")
    return head + "\n[output truncated]", True


def _parse_result(logs: bytes) -> dict[str, Any] | None:
    line = logs.rstrip().rsplit(b"\n", 1)[-1]
    try:
        data = json.loads(line)
    except ValueError:
        return None
    return data if isinstance(data, dict) and "exit_code" in data else None


class Executor:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.s = settings
        self.client = client or docker.DockerClient(base_url=settings.SANDBOX_DOCKER_HOST)
        self._live: dict[str, Any] = {}
        self._lock = threading.Lock()

    def ping(self) -> bool:
        try:
            self.client.ping()
            self.client.images.get(self.s.SANDBOX_IMAGE)
            return True
        except Exception:
            return False

    def _create(self, execution_id: str) -> Any:
        return self.client.containers.create(
            self.s.SANDBOX_IMAGE,
            runtime=self.s.SANDBOX_RUNTIME,
            network_mode="none",
            network_disabled=True,
            read_only=True,
            tmpfs=limits.TMPFS,
            user="65534:65534",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            mem_limit=limits.MEMORY_BYTES,
            memswap_limit=limits.MEMORY_BYTES,
            nano_cpus=limits.NANO_CPUS,
            pids_limit=limits.PIDS_LIMIT,
            ulimits=[
                Ulimit(name=u["Name"], soft=u["Soft"], hard=u["Hard"]) for u in limits.ULIMITS
            ],
            environment=limits.ENV,
            labels={
                "nova.sandbox": "1",
                "nova.execution_id": execution_id,
                "nova.expires_at": str(int(time.time()) + limits.CONTAINER_TTL_SECONDS),
            },
            working_dir="/work",
            stdin_open=True,
            detach=True,
        )

    def run(
        self, execution_id: str, code: str, timeout_seconds: int, files: list[InputFile]
    ) -> Result:
        container = self._create(execution_id)
        with self._lock:
            self._live[execution_id] = container
        started = time.monotonic()
        try:
            payload = (
                json.dumps(
                    {
                        "code": code,
                        "timeout_seconds": timeout_seconds,
                        "files": [
                            {"name": f.name, "content_b64": base64.b64encode(f.content).decode()}
                            for f in files
                        ],
                    }
                ).encode()
                + b"\n"
            )  # one line; the harness reads exactly one line
            # Code is delivered over stdin: the rootfs is read-only and the /work tmpfs only
            # exists while the container runs (see infra/docker/sandbox-python/run.py).
            sock = container.attach_socket(params={"stdin": 1, "stream": 1})
            container.start()
            raw = getattr(sock, "_sock", sock)
            raw.sendall(payload)
            with contextlib.suppress(Exception):
                raw.shutdown(socket.SHUT_WR)
            sock.close()
            hard_timeout = False
            try:
                container.wait(timeout=timeout_seconds + 2)
            except Exception:
                hard_timeout = True
                with contextlib.suppress(Exception):
                    container.kill()
            duration = int((time.monotonic() - started) * 1000)
            container.reload()
            state = container.attrs.get("State", {})
            oom = bool(state.get("OOMKilled"))
            logs: bytes = container.logs(stdout=True, stderr=False)
            parsed = _parse_result(logs)
            if parsed is not None and not hard_timeout:
                return Result(
                    execution_id,
                    int(parsed["exit_code"]),
                    str(parsed["stdout"]),
                    str(parsed["stderr"]),
                    bool(parsed["timed_out"]),
                    bool(parsed["truncated"]),
                    duration,
                    oom,
                    list(parsed["images"])[: limits.MAX_IMAGES],
                )
            # Killed before reporting (OOM, hard timeout, crash): fall back to raw output.
            stderr, _ = _cap(container.logs(stdout=False, stderr=True))
            if oom:
                stderr = (stderr + "\nMemoryError: the program exceeded 256 MB").strip()
            exit_code = None if hard_timeout else int(state.get("ExitCode", -1))
            return Result(execution_id, exit_code, "", stderr, hard_timeout, False, duration, oom)
        finally:
            with self._lock:
                self._live.pop(execution_id, None)
            with contextlib.suppress(Exception):
                container.remove(force=True)

    def cancel(self, execution_id: str) -> bool:
        with self._lock:
            c = self._live.get(execution_id)
        if c is None:
            return False
        try:
            c.kill()
        except Exception:
            pass
        return True

    def reap_orphans(self) -> int:
        now = int(time.time())
        removed = 0
        for c in self.client.containers.list(all=True, filters={"label": "nova.sandbox=1"}):
            if int(c.labels.get("nova.expires_at", "0")) < now:
                try:
                    c.remove(force=True)
                    removed += 1
                except Exception:
                    pass
        return removed
