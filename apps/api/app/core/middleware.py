"""Pure-ASGI middleware: request id, proxy secret, security headers, access log (docs/05 §3).

Implemented as raw ASGI (not BaseHTTPMiddleware) so SSE responses stream without buffering.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.security import constant_time_eq

log = structlog.get_logger("app.http")

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PROXY_EXEMPT_PATHS = {"/healthz", "/readyz"}
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"x-frame-options", b"DENY"),
    (b"cache-control", b"no-store"),
]


def _header(scope: Scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return str(v.decode("latin-1"))
    return None


class RequestContextMiddleware:
    """Assigns X-Request-ID, binds log context, enforces the proxy secret, adds headers, logs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = _header(scope, b"x-request-id")
        request_id = incoming if incoming and _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        path: str = scope["path"]
        start = time.perf_counter()
        status_holder: dict[str, Any] = {"status": 500}

        settings = get_settings()
        if path not in PROXY_EXEMPT_PATHS:
            provided = _header(scope, b"x-nova-proxy-secret") or ""
            expected = settings.API_PROXY_SHARED_SECRET.get_secret_value()
            if not constant_time_eq(provided, expected):
                log.warning("security.proxy_secret_invalid", path=path)
                await _send_plain(send, 404, request_id)
                return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                headers.append((b"x-request-id", request_id.encode()))
                headers.extend(h for h in SECURITY_HEADERS if h[0] not in existing)
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if path not in PROXY_EXEMPT_PATHS:
                status = status_holder["status"]
                level = "error" if status >= 500 else ("warning" if status in (429,) else "info")
                route = scope.get("route")
                getattr(log, level)(
                    "http.request.completed",
                    method=scope["method"],
                    route=getattr(route, "path", path),
                    status_code=status,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                )


async def _send_plain(send: Send, status: int, request_id: str) -> None:
    body = (
        b'{"error":{"code":"RESOURCE_NOT_FOUND","message":"Not found.","details":[],'
        b'"request_id":"' + request_id.encode() + b'","retryable":false}}'
    )
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"x-request-id", request_id.encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
