"""Envelope and base schemas (docs/30 §5)."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class In(BaseModel):
    """Base for request bodies: reject unknown fields, strip strings."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel):
    next_cursor: str | None = None
    has_more: bool = False


class Envelope(BaseModel, Generic[T]):
    data: T
    meta: dict[str, Any] | None = None


class ListEnvelope(BaseModel, Generic[T]):
    data: list[T]
    page: Page = Page()
    meta: dict[str, Any] | None = None
