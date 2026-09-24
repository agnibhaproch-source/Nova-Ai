"""Prompt templates rendered with Jinja2 (StrictUndefined)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_DIR = Path(__file__).parent
_TAGS = (
    "retrieved_documents",
    "user_memories",
    "conversation_summary",
    "user_instructions",
    "about_user",
)
_TAG_RE = re.compile(r"</?\s*(" + "|".join(_TAGS) + r")\s*>", re.IGNORECASE)


@lru_cache
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_DIR)),
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def render(name: str, **ctx: Any) -> str:
    return _env().get_template(name).render(**ctx).strip()


def neutralize(data: str) -> str:
    """Neutralize our delimiter tags inside untrusted data (docs/33 §8)."""
    return _TAG_RE.sub(lambda m: m.group(0).replace("<", "‹"), data)
