"""Model registry loaded from config/models.yaml with env interpolation (docs/15)."""

from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import structlog
import yaml
from pydantic import BaseModel, Field, PositiveInt

from app.core.errors import AppError, ErrorCode

log = structlog.get_logger()
_VAR = re.compile(r"\$\{([A-Z0-9_]+)(:-([^}]*))?\}")


class Pricing(BaseModel):
    input_per_million_usd: Decimal | None = None
    output_per_million_usd: Decimal | None = None


class ModelConfig(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,31}$")
    groq_model_id: str
    display_name: str
    description: str = ""
    enabled: bool = True
    context_window: PositiveInt | None
    max_output_tokens: PositiveInt | None
    default_max_output_tokens: PositiveInt
    default_temperature: float = Field(ge=0, le=2)
    default_top_p: float = Field(gt=0, le=1)
    supports_streaming: bool = True
    supports_tools: bool | None
    supports_parallel_tool_calls: bool = False
    supports_json_mode: bool | None
    supports_vision: bool = False
    max_images_per_request: PositiveInt | None = None
    max_image_bytes: PositiveInt = 4 * 1024 * 1024
    image_token_cost: PositiveInt = 1500
    token_estimate_bytes_per_token: float = Field(default=3.2, gt=1, le=8)
    fallback_key: str | None = None
    plans: list[Literal["free", "plus", "pro"]]
    pricing: Pricing = Pricing()
    deprecation_date: date | None = None


class Defaults(BaseModel):
    model_key: str
    purposes: dict[str, str]


class RegistryFile(BaseModel):
    version: int
    defaults: Defaults
    models: list[ModelConfig]


class RegistryInvalid(Exception):
    pass


def _interpolate(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name, has_default, default = m.group(1), m.group(2), m.group(3)
        value = os.environ.get(name, "")
        if not value:
            from app.core.config import get_settings

            value = str(getattr(get_settings(), name, "") or "")
        if value:
            return value
        if has_default is not None:
            return default or ""
        raise RegistryInvalid(f"{name} is not set (required by models.yaml)")

    return _VAR.sub(repl, text)


class ModelRegistry:
    def __init__(self, data: RegistryFile) -> None:
        self.defaults = data.defaults
        self._models = {m.key: m for m in data.models}
        self.disabled_keys: set[str] = set()

    @classmethod
    def load(cls, path: Path) -> ModelRegistry:
        raw = yaml.safe_load(_interpolate(path.read_text()))
        # Required env interpolation failures raise RegistryInvalid above; empty optional ids
        # disable the entry.
        for m in raw.get("models", []):
            if not m.get("groq_model_id"):
                m["enabled"] = False
                m["groq_model_id"] = ""
        reg = cls(RegistryFile.model_validate(raw))
        reg.validate_static()
        return reg

    def validate_static(self) -> None:
        enabled = {k for k, m in self._models.items() if m.enabled}
        needed = {self.defaults.model_key, *self.defaults.purposes.values()}
        missing = needed - enabled
        if missing:
            raise RegistryInvalid(f"default/purpose models not enabled: {sorted(missing)}")
        for m in self._models.values():
            if m.fallback_key and m.fallback_key not in enabled:
                m.fallback_key = None

    def validate_complete(self) -> None:
        """Every enabled model must have facts that are never guessed (docs/15 §4 step 5)."""
        for m in self._models.values():
            if not m.enabled:
                continue
            for f in (
                "context_window",
                "max_output_tokens",
                "supports_tools",
                "supports_json_mode",
            ):
                if getattr(m, f) is None:
                    raise RegistryInvalid(
                        f"models.yaml: '{m.key}.{f}' is null — set it from Groq documentation"
                    )
            assert m.max_output_tokens and m.context_window
            if m.default_max_output_tokens > m.max_output_tokens:
                raise RegistryInvalid(f"{m.key}: default_max_output_tokens > max_output_tokens")

    def adopt_context_windows(self, reported: dict[str, int]) -> None:
        for m in self._models.values():
            if m.context_window is None and m.groq_model_id in reported:
                m.context_window = reported[m.groq_model_id]
                log.info("model_registry.adopted", model_key=m.key, field="context_window")

    def all(self) -> list[ModelConfig]:
        return list(self._models.values())

    def is_enabled(self, key: str) -> bool:
        m = self._models.get(key)
        return bool(m and m.enabled and key not in self.disabled_keys)

    def resolve(self, key: str | None) -> ModelConfig:
        key = key or self.defaults.model_key
        if not self.is_enabled(key):
            raise AppError(ErrorCode.MODEL_NOT_AVAILABLE)
        return self._models[key]

    def for_purpose(self, purpose: str) -> ModelConfig:
        key = self.defaults.purposes.get(purpose, self.defaults.model_key)
        if not self.is_enabled(key):
            key = self.defaults.model_key
        return self.resolve(key)

    def list_for_plan(self, plan: str, plan_models: list[str] | None = None) -> list[ModelConfig]:
        return [
            m
            for m in self._models.values()
            if self.is_enabled(m.key)
            and plan in m.plans
            and (plan_models is None or m.key in plan_models)
        ]


_registry: ModelRegistry | None = None
_registry_error: str | None = None


def init_registry(path: Path) -> None:
    global _registry, _registry_error
    try:
        _registry = ModelRegistry.load(path)
        _registry_error = None
    except (RegistryInvalid, ValueError) as e:
        _registry, _registry_error = None, str(e)
        raise


def get_registry() -> ModelRegistry:
    if _registry is None:
        log.error("model_registry.unavailable", reason=_registry_error)
        raise AppError(
            ErrorCode.MODEL_NOT_AVAILABLE,
            "No AI model is configured yet. An administrator must set the Groq model settings.",
        )
    return _registry


def set_registry(reg: ModelRegistry | None) -> None:
    global _registry
    _registry = reg


def registry_error() -> str | None:
    return _registry_error
