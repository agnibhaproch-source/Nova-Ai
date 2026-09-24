"""ToolRegistry + ToolEngine: explicit allow-list, permissions, validation, timeouts,
persistence and SSE events (docs/22). The model can only *request*; the server decides."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import ValidationError

from app.ai.models_registry import ModelConfig
from app.ai.provider import LLMToolCall, ToolSchema
from app.core.config import get_settings
from app.core.redis import get_redis, rkey
from app.db.session import get_sessionmaker
from app.models import ToolCall
from app.ratelimit import limiter
from app.services.usage_service import record as record_usage
from app.tools.base import Tool, ToolContext, ToolError, ToolResult
from app.tools.calculator import CalculatorTool
from app.tools.code_execution import CodeExecutionTool
from app.tools.file_search import FileSearchTool
from app.tools.web_search import WebSearchTool

log = structlog.get_logger("app.tools")
MAX_ITERATIONS = 5
MAX_CALLS_PER_TURN = 8
MAX_CALLS_PER_TOOL = 3
RESULT_CAP_BYTES = 256 * 1024


def build_registry() -> dict[str, Tool]:
    s = get_settings()
    tools: list[Tool] = [CalculatorTool(), FileSearchTool()]
    if s.WEB_SEARCH_PROVIDER != "none":
        tools.append(WebSearchTool())
    if s.SANDBOX_RUNNER_URL:
        tools.append(CodeExecutionTool())
    return {t.name: t for t in tools}


def registry() -> dict[str, Tool]:
    return build_registry()


def disabled_reason(
    tool: Tool,
    *,
    model: ModelConfig | None,
    limits: dict[str, Any],
    prefs: Any,
    disabled_tools: list[str],
    has_files: bool,
    toggles: dict[str, bool] | None,
) -> str | None:
    if model is not None and not model.supports_tools:
        return "model"
    if tool.name in disabled_tools:
        return "admin"
    if tool.name not in limits.get("tools", []):
        return "plan"
    if tool.requires_preference and not getattr(prefs, tool.requires_preference, True):
        return "preference"
    if toggles is not None and toggles.get(tool.name) is False:
        return "preference"
    if tool.name == "file_search" and not has_files:
        return "no_files"
    return None


def schemas(tools: list[Tool]) -> list[ToolSchema]:
    return [
        ToolSchema(name=t.name, description=t.description, parameters=t.schema()) for t in tools
    ]


@dataclass
class Executed:
    call: LLMToolCall
    row_id: uuid.UUID
    tool_name: str
    result: ToolResult


class ToolEngine:
    def __init__(self, available: list[Tool], ctx: ToolContext, publish: Any) -> None:
        self.tools = {t.name: t for t in available}
        self.ctx = ctx
        self.publish = publish  # async (event, data) -> None
        self.calls_total = 0
        self.calls_per_tool: dict[str, int] = {}
        self.corrections: set[str] = set()

    async def _quota_ok(self, tool: Tool) -> bool:
        if not tool.quota_key:
            return True
        limit = int(self.ctx.limits.get(tool.quota_key, 0))
        key = rkey("q", tool.name, self.ctx.user_id, datetime.now(UTC).strftime("%Y%m%d"))
        try:
            n = int(await get_redis().incr(key))
            await get_redis().expire(key, 48 * 3600)
        except Exception:
            return True
        return n <= limit

    async def execute_all(
        self, calls: list[LLMToolCall], iteration: int, next_position: Any
    ) -> list[Executed]:
        out = []
        for call in calls[:4]:
            out.append(await self._execute(call, iteration, next_position))
        return out

    async def _execute(self, call: LLMToolCall, iteration: int, next_position: Any) -> Executed:
        ctx = self.ctx
        tool = self.tools.get(call.name)
        args_obj: Any = None
        try:
            parsed = (
                json.loads(call.arguments_json or "{}")
                if len(call.arguments_json or "") <= 32_768
                else None
            )
            if parsed is None:
                raise ValueError("arguments too large")
        except (ValueError, json.JSONDecodeError):
            parsed = {}
        async with get_sessionmaker()() as db:
            row = ToolCall(
                message_id=ctx.message_id,
                conversation_id=ctx.conversation_id,
                user_id=ctx.user_id,
                provider_tool_call_id=call.id[:128],
                iteration=min(iteration, 10),
                tool_name=call.name[:64],
                arguments=parsed if isinstance(parsed, dict) else {},
                status="pending",
            )
            db.add(row)
            await db.commit()
            row_id = row.id
        call_pos = next_position()
        denied = self._deny_reason(call.name, tool)
        if denied is None and tool is not None and not await self._quota_ok(tool):
            denied = ("QUOTA_EXCEEDED", "Daily limit for this tool reached; answer without it.")
        if denied is None and tool is not None:
            d = await limiter.check(
                f"tool_{tool.name}" if f"tool_{tool.name}" in limiter.POLICIES else "api_write",
                f"user:{ctx.user_id}",
                plan=ctx.plan_key,
            )
            if not d.allowed:
                denied = ("RATE_LIMITED", "Tool rate limit reached; answer without it.")
        started = time.monotonic()
        if denied is not None or tool is None:
            code, msg = denied or ("TOOL_NOT_FOUND", f"Tool {call.name} is not available.")
            result = ToolResult(
                "denied", json.dumps({"error": code, "detail": msg}), msg, error_code=code
            )
            await self._persist(
                row_id,
                "denied",
                result,
                call_pos,
                started,
                tool_name=call.name,
                label=call.name,
                args={},
            )
            return Executed(call, row_id, call.name, result)
        try:
            args_obj = tool.Args.model_validate(parsed)
        except ValidationError as e:
            detail = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
            result = ToolResult(
                "failed",
                json.dumps({"error": "INVALID_ARGUMENTS", "detail": detail[:500]}),
                "Invalid arguments",
                error_code="INVALID_ARGUMENTS",
            )
            await self._persist(
                row_id,
                "failed",
                result,
                call_pos,
                started,
                tool_name=tool.name,
                label=tool.display_name,
                args=parsed,
            )
            return Executed(call, row_id, tool.name, result)
        label = tool.label(args_obj)
        await self.publish(
            "tool_start",
            {
                "message_id": str(ctx.message_id),
                "tool_call_id": str(row_id),
                "tool_name": tool.name,
                "label": label,
                "arguments": _display_args(tool, args_obj),
                "part_position": call_pos,
            },
        )
        async with get_sessionmaker()() as db:
            r = await db.get(ToolCall, row_id)
            if r:
                r.status, r.started_at = "running", datetime.now(UTC)
                await db.commit()
        try:
            result = await asyncio.wait_for(tool.run(args_obj, ctx), tool.timeout_seconds)
        except TimeoutError:
            result = ToolResult(
                "timed_out",
                json.dumps({"error": "TOOL_TIMEOUT"}),
                "Timed out",
                error_code="TOOL_TIMEOUT",
            )
        except ToolError as e:
            result = ToolResult(
                "failed",
                json.dumps({"error": e.code, "detail": e.message}),
                e.message,
                error_code=e.code,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("tool.unhandled", tool_name=tool.name)
            result = ToolResult(
                "failed",
                json.dumps({"error": "TOOL_ERROR"}),
                "Tool failed",
                error_code="TOOL_ERROR",
            )
        await self._persist(
            row_id,
            result.status,
            result,
            call_pos,
            started,
            tool_name=tool.name,
            label=label,
            args=_display_args(tool, args_obj),
        )
        return Executed(call, row_id, tool.name, result)

    def _deny_reason(self, name: str, tool: Tool | None) -> tuple[str, str] | None:
        if tool is None:
            return (
                "TOOL_NOT_ALLOWED" if name in registry() else "TOOL_NOT_FOUND",
                f"Tool {name} is not available for this user; answer without it.",
            )
        if (
            self.calls_total >= MAX_CALLS_PER_TURN
            or self.calls_per_tool.get(name, 0) >= MAX_CALLS_PER_TOOL
        ):
            return ("TOOL_LIMIT_REACHED", "Tool call limit reached for this answer.")
        self.calls_total += 1
        self.calls_per_tool[name] = self.calls_per_tool.get(name, 0) + 1
        return None

    async def _persist(
        self,
        row_id: uuid.UUID,
        status: str,
        result: ToolResult,
        call_pos: int,
        started: float,
        *,
        tool_name: str,
        label: str,
        args: dict[str, Any],
    ) -> None:
        from app.models import MessagePart

        latency = int((time.monotonic() - started) * 1000)
        stored: dict[str, Any] = {
            "summary": result.summary,
            "display": result.display,
            "citations": result.citations,
        }
        blob = json.dumps(stored, default=str)
        if len(blob) > RESULT_CAP_BYTES:
            stored = {"summary": result.summary, "truncated": True}
        async with get_sessionmaker()() as db:
            r = await db.get(ToolCall, row_id)
            if r is not None:
                r.status, r.result, r.error_code = status, stored, result.error_code
                r.error_message = result.summary if result.error_code else None
                r.completed_at, r.latency_ms = datetime.now(UTC), latency
            db.add(
                MessagePart(
                    message_id=self.ctx.message_id,
                    position=call_pos,
                    type="tool_call",
                    tool_call_id=row_id,
                    data={"tool_name": tool_name, "arguments": args, "label": label},
                )
            )
            part_type = "code" if result.code else "tool_result"
            db.add(
                MessagePart(
                    message_id=self.ctx.message_id,
                    position=call_pos + 1,
                    type=part_type,
                    tool_call_id=row_id,
                    text_content=(result.code or {}).get("code") if result.code else None,
                    data=(
                        {k: v for k, v in (result.code or {}).items() if k != "code"}
                        if result.code
                        else {
                            "tool_name": tool_name,
                            "status": status,
                            "summary": result.summary,
                            "display": result.display,
                            "error_code": result.error_code,
                        }
                    ),
                )
            )
            if tool_name in ("web_search", "code_execution") and status == "succeeded":
                record_usage(
                    db,
                    kind=tool_name,
                    model=None,
                    usage=None,
                    request_id=self.ctx.request_id,
                    user_id=self.ctx.user_id,
                    conversation_id=self.ctx.conversation_id,
                    message_id=self.ctx.message_id,
                    latency_ms=latency,
                    provider="search" if tool_name == "web_search" else "sandbox",
                )
            await db.commit()
        log.info(
            "tool.call.completed",
            tool_name=tool_name,
            status=status,
            latency_ms=latency,
            error_code=result.error_code,
        )
        await self.publish(
            "tool_result",
            {
                "message_id": str(self.ctx.message_id),
                "tool_call_id": str(row_id),
                "tool_name": tool_name,
                "status": status,
                "summary": result.summary,
                "display": result.display,
                "latency_ms": latency,
                "part_position": call_pos + 1,
                "code": result.code,
            },
        )


def _display_args(tool: Tool, args: Any) -> dict[str, Any]:
    data: dict[str, Any] = args.model_dump() if hasattr(args, "model_dump") else dict(args)
    return data
