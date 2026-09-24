"""code_execution: Python in the isolated sandbox (gVisor, no network) (docs/24)."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Literal

from pydantic import Field

from app.db.session import get_sessionmaker
from app.files import storage
from app.models import File
from app.sandbox import client as sandbox
from app.tools.base import Tool, ToolArgs, ToolContext, ToolError, ToolResult

OUTPUT_LIMIT = 8000


def _tail(s: str, limit: int) -> str:
    return s if len(s) <= limit else f"…[truncated {len(s) - limit} chars]…\n" + s[-limit:]


class CodeExecutionTool(Tool):
    name = "code_execution"
    display_name = "Python"
    description = (
        "Run Python 3.12 code in an isolated sandbox with numpy, pandas, scipy, "
        "sympy and matplotlib. No internet access. Print results to stdout. "
        "Use for calculations, data analysis and plots."
    )
    timeout_seconds = 30.0
    quota_key = "code_executions_per_day"
    requires_preference = "code_execution_enabled"

    class Args(ToolArgs):
        language: Literal["python"] = "python"
        code: str = Field(min_length=1, max_length=20_000)

    def label(self, args: Any) -> str:
        return "Running Python"

    async def run(self, args: Any, ctx: ToolContext) -> ToolResult:
        exec_id = str(uuid.uuid4())
        timeout = int(ctx.limits.get("code_timeout_seconds", 10))
        task = asyncio.create_task(sandbox.execute(exec_id, args.code, timeout))
        cancel_wait = asyncio.create_task(ctx.cancel_event.wait())
        done, _ = await asyncio.wait({task, cancel_wait}, return_when=asyncio.FIRST_COMPLETED)
        if cancel_wait in done:
            task.cancel()
            await sandbox.cancel(exec_id)
            raise asyncio.CancelledError
        cancel_wait.cancel()
        try:
            out = task.result()
        except sandbox.SandboxBusy as e:
            raise ToolError("SANDBOX_BUSY", "The code sandbox is busy. Try again.") from e
        except sandbox.SandboxUnavailable as e:
            raise ToolError("TOOL_ERROR", "Code execution is unavailable right now.") from e
        image_ids = await self._store_images(ctx, out.get("images") or [])
        stdout, stderr = str(out.get("stdout", "")), str(out.get("stderr", ""))
        code_part = {
            "language": "python",
            "code": args.code,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": out.get("exit_code"),
            "timed_out": bool(out.get("timed_out")),
            "truncated": bool(out.get("truncated")),
            "duration_ms": out.get("duration_ms"),
            "images": image_ids,
        }
        model = {
            "tool": "code_execution",
            "untrusted_content": True,
            "exit_code": out.get("exit_code"),
            "timed_out": bool(out.get("timed_out")),
            "stdout": _tail(stdout, OUTPUT_LIMIT),
            "stderr": _tail(stderr, 3000),
            "images": [i["name"] for i in out.get("images") or []],
        }
        status: Literal["timed_out", "succeeded"] = (
            "timed_out" if out.get("timed_out") else "succeeded"
        )
        summary = "Timed out" if out.get("timed_out") else f"Exit code {out.get('exit_code')}"
        return ToolResult(status, json.dumps(model), summary, display=code_part, code=code_part)

    async def _store_images(self, ctx: ToolContext, images: list[dict[str, str]]) -> list[str]:
        ids: list[str] = []
        for img in images[:3]:
            data = sandbox.decode_image(img["content_b64"])
            if len(data) > 1024 * 1024:
                continue
            fid = uuid.uuid4()
            key = f"users/{ctx.user_id}/files/{fid}"
            await storage.put(key, data, "image/png")
            await storage.put(f"{key}/derived/display.webp", data, "image/png")
            async with get_sessionmaker()() as db:
                db.add(
                    File(
                        id=fid,
                        user_id=ctx.user_id,
                        original_filename=img["name"],
                        extension="png",
                        declared_mime_type="image/png",
                        detected_mime_type="image/png",
                        size_bytes=len(data),
                        storage_key=key,
                        kind="image",
                        status="ready",
                        metadata_={"source": "code_execution"},
                    )
                )
                await db.commit()
            ids.append(str(fid))
        return ids
