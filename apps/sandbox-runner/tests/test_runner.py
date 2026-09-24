"""Runner unit tests with a fake Docker client (docs/24 §11)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sandbox_runner.config import Settings
from sandbox_runner.executor import Executor
from sandbox_runner.main import create_app

TOKEN = "t" * 40


class FakeSock:
    def __init__(self, owner: FakeContainer) -> None:
        self.owner = owner

    def sendall(self, data: bytes) -> None:
        self.owner.stdin += data

    def shutdown(self, how: int) -> None: ...
    def close(self) -> None: ...


class FakeContainer:
    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour
        self.removed = self.killed = False
        self.stdin = b""
        oom = behaviour == "oom"
        self.attrs: dict[str, Any] = {"State": {"OOMKilled": oom, "ExitCode": 137 if oom else 0}}
        self.labels = {"nova.sandbox": "1", "nova.expires_at": "0"}

    def attach_socket(self, params: dict[str, int]) -> FakeSock:
        return FakeSock(self)

    def start(self) -> None: ...
    def wait(self, timeout: int) -> dict[str, int]:
        if self.behaviour == "hang":
            raise TimeoutError
        return {"StatusCode": 0}

    def kill(self) -> None:
        self.killed = True

    def logs(self, stdout: bool, stderr: bool) -> bytes:
        if not stdout or self.behaviour in ("oom", "hang"):
            return b""
        result = {
            "exit_code": 0,
            "stdout": "2\n",
            "stderr": "",
            "timed_out": False,
            "truncated": False,
            "images": [{"name": f"figure{i}.png", "content_b64": "eA=="} for i in range(5)],
        }
        return b"noise from user code\n" + json.dumps(result).encode() + b"\n"

    def reload(self) -> None: ...
    def remove(self, force: bool) -> None:
        self.removed = True


class FakeDocker:
    def __init__(self, behaviour: str = "ok") -> None:
        self.behaviour = behaviour
        self.created: list[dict[str, Any]] = []
        self.last: FakeContainer | None = None
        self.containers = self
        self.images = self

    def create(self, image: str, **kw: Any) -> FakeContainer:
        self.created.append(kw)
        self.last = FakeContainer(self.behaviour)
        return self.last

    def list(self, all: bool, filters: dict[str, str]) -> list[FakeContainer]:
        return [FakeContainer("ok")]

    def get(self, name: str) -> None: ...
    def ping(self) -> bool:
        return True


def make(behaviour: str = "ok") -> tuple[TestClient, FakeDocker]:
    s = Settings(SANDBOX_RUNNER_TOKEN=TOKEN, SANDBOX_RUNTIME="runc", APP_ENV="test")  # type: ignore[arg-type]
    fake = FakeDocker(behaviour)
    return TestClient(create_app(s, Executor(s, client=fake))), fake


AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"execution_id": "exec-12345678", "code": "print(1+1)", "timeout_seconds": 5}


def test_requires_token() -> None:
    c, _ = make()
    assert c.post("/v1/execute", json=BODY).status_code == 401
    assert (
        c.post("/v1/execute", json=BODY, headers={"Authorization": "Bearer nope"}).status_code
        == 401
    )


def test_executes_with_locked_down_container() -> None:
    c, fake = make()
    r = c.post("/v1/execute", json=BODY, headers=AUTH)
    assert r.status_code == 200
    d = r.json()
    assert d["exit_code"] == 0 and d["stdout"] == "2\n" and not d["timed_out"]
    assert len(d["images"]) == 3  # capped
    kw = fake.created[0]
    assert kw["network_mode"] == "none" and kw["read_only"] is True
    assert kw["cap_drop"] == ["ALL"] and kw["user"] == "65534:65534"
    assert kw["pids_limit"] == 64 and kw["mem_limit"] == kw["memswap_limit"]
    assert "no-new-privileges:true" in kw["security_opt"]
    assert set(kw["environment"]) == {"PYTHONUNBUFFERED", "MPLBACKEND", "HOME"}
    assert fake.last is not None and fake.last.removed
    sent = json.loads(fake.last.stdin)
    assert fake.last.stdin.endswith(b"\n") and sent["code"] == "print(1+1)"
    assert sent["timeout_seconds"] == 5


def test_hard_timeout_kills_and_removes() -> None:
    c, fake = make("hang")
    d = c.post("/v1/execute", json=BODY, headers=AUTH).json()
    assert d["timed_out"] and d["exit_code"] is None and d["images"] == []
    assert fake.last is not None and fake.last.killed and fake.last.removed


def test_oom_falls_back_to_container_state() -> None:
    c, _ = make("oom")
    d = c.post("/v1/execute", json=BODY, headers=AUTH).json()
    assert d["oom_killed"] is True and d["exit_code"] == 137 and "256 MB" in d["stderr"]


def test_rejects_bad_input_files() -> None:
    c, _ = make()
    bad = {
        **BODY,
        "files": [{"name": "../etc/passwd", "content_b64": base64.b64encode(b"x").decode()}],
    }
    assert c.post("/v1/execute", json=bad, headers=AUTH).status_code == 422


def test_production_requires_gvisor() -> None:
    with pytest.raises(ValueError, match="runsc"):
        Settings(SANDBOX_RUNNER_TOKEN=TOKEN, SANDBOX_RUNTIME="runc", APP_ENV="production")  # type: ignore[arg-type]
