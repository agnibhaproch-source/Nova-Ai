"""SandboxClient: the only path to code execution (sandbox-runner service, docs/24).
User/model code never runs inside the API or worker process."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.config import get_settings


class SandboxUnavailable(Exception):
    pass


class SandboxBusy(Exception):
    pass


async def execute(
    execution_id: str, code: str, timeout_seconds: int, files: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    s = get_settings()
    if not s.SANDBOX_RUNNER_URL or not s.SANDBOX_RUNNER_TOKEN:
        raise SandboxUnavailable("sandbox runner not configured")
    headers = {"Authorization": f"Bearer {s.SANDBOX_RUNNER_TOKEN.get_secret_value()}"}
    body = {
        "execution_id": execution_id,
        "language": "python",
        "code": code,
        "timeout_seconds": timeout_seconds,
        "files": files or [],
    }
    async with httpx.AsyncClient(
        base_url=s.SANDBOX_RUNNER_URL, headers=headers, timeout=timeout_seconds + 15
    ) as c:
        for attempt in range(2):
            try:
                r = await c.post("/v1/execute", json=body)
            except httpx.HTTPError as e:
                raise SandboxUnavailable(str(e)) from e
            if r.status_code == 429 and attempt == 0:
                import asyncio

                await asyncio.sleep(1)
                continue
            if r.status_code == 429:
                raise SandboxBusy
            if r.status_code >= 400:
                raise SandboxUnavailable(f"runner status {r.status_code}")
            data: dict[str, Any] = r.json()
            return data
    raise SandboxBusy


async def cancel(execution_id: str) -> None:
    s = get_settings()
    if not s.SANDBOX_RUNNER_URL or not s.SANDBOX_RUNNER_TOKEN:
        return
    try:
        async with httpx.AsyncClient(
            base_url=s.SANDBOX_RUNNER_URL,
            timeout=5,
            headers={"Authorization": f"Bearer {s.SANDBOX_RUNNER_TOKEN.get_secret_value()}"},
        ) as c:
            await c.delete(f"/v1/executions/{execution_id}")
    except httpx.HTTPError:
        pass


def decode_image(b64: str) -> bytes:
    return base64.b64decode(b64)
