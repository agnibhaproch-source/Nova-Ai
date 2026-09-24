"""Structured JSON logging with secret redaction (docs/38_LOGGING.md)."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

from app.core.config import get_settings

_SENSITIVE_KEY = re.compile(
    r"(?i)(pass(word)?|secret|token|api[_-]?key|authorization|cookie|signature|key_secret|dsn)"
)
_SECRET_VALUE = re.compile(
    r"(gsk_[A-Za-z0-9]{20,}|nova_sk_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|-----BEGIN [A-Z ]+-----|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
)
_ALLOWED_KEYS = {"event", "level", "timestamp", "logger", "request_id", "trace_id", "span_id"}


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        value = _SECRET_VALUE.sub("[REDACTED]", value)
        return value if len(value) <= 2000 else value[:2000] + "…"
    if isinstance(value, dict):
        return {k: _redact_pair(k, v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(v) for v in value]
    return value


def _redact_pair(key: str, value: Any) -> Any:
    if key not in _ALLOWED_KEYS and _SENSITIVE_KEY.search(key) and not key.endswith("_count"):
        return "[REDACTED]"
    return _redact_value(value)


def redact_sensitive(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return {k: _redact_pair(k, v) for k, v in event_dict.items()}


def _add_service_fields(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    event_dict.setdefault("service", "nova-api")
    event_dict["env"] = s.APP_ENV
    event_dict["version"] = s.APP_VERSION
    return event_dict


def configure_logging(service: str = "nova-api") -> None:
    s = get_settings()
    level = getattr(logging, s.LOG_LEVEL.upper(), logging.INFO)
    renderer: Any = (
        structlog.dev.ConsoleRenderer()
        if s.LOG_FORMAT == "console"
        else structlog.processors.JSONRenderer()
    )
    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_service_fields,
        redact_sensitive,
    ]
    structlog.configure(
        processors=[
            *shared,
            *([] if s.LOG_FORMAT == "console" else [structlog.processors.dict_tracebacks]),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("sqlalchemy.engine", "httpx", "httpcore", "uvicorn.access", "arq.worker"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


log = structlog.get_logger()
