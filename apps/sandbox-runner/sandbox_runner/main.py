"""FastAPI app: POST /v1/execute, DELETE /v1/executions/{id}, GET /healthz (docs/24 §5)."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from sandbox_runner import limits
from sandbox_runner.config import Settings, get_settings
from sandbox_runner.executor import Executor, InputFile
from sandbox_runner.pool import Busy, Pool, reaper

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class FileIn(BaseModel):
    name: str = Field(max_length=100)
    content_b64: str


class ExecuteIn(BaseModel):
    execution_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    language: Literal["python"] = "python"
    code: str = Field(min_length=1, max_length=limits.MAX_CODE_CHARS)
    timeout_seconds: int = Field(default=10, ge=1, le=limits.MAX_TIMEOUT_SECONDS)
    files: list[FileIn] = Field(default_factory=list, max_length=limits.MAX_INPUT_FILES)


def create_app(settings: Settings | None = None, executor: Executor | None = None) -> FastAPI:
    s = settings or get_settings()
    ex = executor or Executor(s)
    pool = Pool(s.SANDBOX_MAX_CONCURRENCY)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(reaper(ex))
        yield
        task.cancel()

    app = FastAPI(title="nova-sandbox-runner", lifespan=lifespan, docs_url=None, redoc_url=None)

    def auth(authorization: str = Header(default="")) -> None:
        expected = f"Bearer {s.SANDBOX_RUNNER_TOKEN.get_secret_value()}"
        if not hmac.compare_digest(authorization.encode(), expected.encode()):
            raise HTTPException(401, "unauthorized")

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        ok = await asyncio.to_thread(ex.ping)
        if not ok:
            raise HTTPException(503, "docker or sandbox image unavailable")
        return {"status": "ok", "runtime": s.SANDBOX_RUNTIME}

    @app.post("/v1/execute", dependencies=[Depends(auth)])
    async def execute(body: ExecuteIn) -> dict[str, Any]:
        files: list[InputFile] = []
        total = 0
        for f in body.files:
            if not SAFE_NAME.match(f.name):
                raise HTTPException(422, "invalid file name")
            try:
                data = base64.b64decode(f.content_b64, validate=True)
            except binascii.Error as e:
                raise HTTPException(422, "invalid file content") from e
            total += len(data)
            if total > limits.MAX_INPUT_BYTES:
                raise HTTPException(413, "input files too large")
            files.append(InputFile(f.name, data))
        try:
            async with pool.slot():
                result = await asyncio.to_thread(
                    ex.run, body.execution_id, body.code, body.timeout_seconds, files
                )
        except Busy as e:
            raise HTTPException(429, "sandbox busy") from e
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(503, "sandbox unavailable") from e
        return asdict(result)

    @app.delete("/v1/executions/{execution_id}", status_code=204, dependencies=[Depends(auth)])
    async def cancel(execution_id: str) -> None:
        await asyncio.to_thread(ex.cancel, execution_id)

    return app


def app_factory() -> FastAPI:
    return create_app()
