"""Tool protocol and shared types (docs/22 §2)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

ToolStatus = Literal["succeeded", "failed", "timed_out", "denied"]


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=False)


@dataclass
class ToolContext:
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    request_id: str
    plan_key: str
    limits: dict[str, Any]
    preferences: Any
    attached_file_ids: list[uuid.UUID]
    cancel_event: asyncio.Event
    citation_offset: int = 0  # web citations continue after RAG indices


@dataclass
class ToolResult:
    status: ToolStatus
    model_content: str
    summary: str
    display: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    code: dict[str, Any] | None = None  # code part payload for code_execution
    error_code: str | None = None


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code)
        self.code = code
        self.message = message


class Tool:
    name: ClassVar[str]
    display_name: ClassVar[str]
    description: ClassVar[str]
    Args: ClassVar[type[ToolArgs]]
    timeout_seconds: ClassVar[float] = 10.0
    requires_preference: ClassVar[str | None] = None

    def label(self, args: Any) -> str:
        return self.display_name

    async def run(self, args: Any, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        s = self.Args.model_json_schema()
        s.pop("title", None)
        for prop in s.get("properties", {}).values():
            prop.pop("title", None)
        s["additionalProperties"] = False
        return s
