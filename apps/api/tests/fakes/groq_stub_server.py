"""TEST/E2E-ONLY: serves tests.fakes.groq_stub over HTTP for full-stack checks (docs/40 §3).
Run: uv run uvicorn tests.fakes.groq_stub_server:app --port 8099
"""

from __future__ import annotations

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from tests.fakes import groq_stub


async def proxy(request: Request) -> Response:
    body = await request.body()
    req = httpx.Request(request.method, str(request.url), headers=request.headers.raw, content=body)
    res = await groq_stub.handler(req)
    headers = {"content-type": res.headers.get("content-type", "application/json")}
    if res.headers.get("content-type", "").startswith("text/event-stream"):
        return StreamingResponse(res.aiter_bytes(), status_code=res.status_code, headers=headers)
    return Response(await res.aread(), status_code=res.status_code, headers=headers)


groq_stub.scenario.reply = (
    "Hello! I'm **Nova**, running against the local Groq stub.\n\n"
    "```python\nprint('streaming works')\n```\n\nMath: $e^{i\\pi} + 1 = 0$"
)
groq_stub.scenario.delay_s = 0.01

app = Starlette(routes=[Route("/{path:path}", proxy, methods=["GET", "POST"])])
