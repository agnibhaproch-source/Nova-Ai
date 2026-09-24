"""Health, readiness, public app config and analytics ingest (docs/31 §1, §4, §14)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_principal, rate_limit
from app.core.config import API_ROOT, get_settings
from app.core.redis import get_redis
from app.db.session import get_db
from app.schemas.common import Envelope, In
from app.services import analytics_service, settings_service

health_router = APIRouter(tags=["health"])
router = APIRouter(tags=["system"])


def _head_revision() -> str | None:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


@health_router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/readyz", include_in_schema=False)
async def readyz(db: AsyncSession = Depends(get_db)) -> Response:
    checks: dict[str, str] = {}
    try:
        rev = await asyncio.wait_for(db.scalar(text("SELECT version_num FROM alembic_version")), 2)
        checks["database"] = "ok"
        checks["migrations"] = "ok" if rev == _head_revision() else "pending"
    except Exception:
        checks["database"] = "down"
        checks["migrations"] = "unknown"
    try:
        await asyncio.wait_for(get_redis().ping(), 1)
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "down"
    from app.ai.models_registry import registry_error

    checks["models"] = "ok" if registry_error() is None else "not_configured"
    ok = all(checks[k] == "ok" for k in ("database", "redis", "migrations"))
    return JSONResponse(
        {"status": "ready" if ok else "not_ready", "checks": checks}, status_code=200 if ok else 503
    )


@router.get("/app-config", operation_id="system_app_config")
async def app_config(
    response: Response, db: AsyncSession = Depends(get_db)
) -> Envelope[dict[str, Any]]:
    values = await settings_service.get_all(db)
    response.headers["Cache-Control"] = "public, max-age=30"
    public = {k: values[k] for k, d in settings_service.REGISTRY.items() if d.public}
    public["groq_key_mode"] = get_settings().GROQ_KEY_MODE
    return Envelope(data=public)


class EventIn(In):
    name: str = Field(max_length=64)
    occurred_at: datetime | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class EventsIn(In):
    anonymous_id: str | None = Field(default=None, max_length=64)
    events: list[EventIn] = Field(max_length=20)


@router.post(
    "/analytics/events",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="analytics_ingest",
    dependencies=[Depends(rate_limit("analytics_ingest"))],
)
async def ingest(
    body: EventsIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> Envelope[dict[str, int]]:
    accepted = 0
    for e in body.events:
        accepted += int(
            await analytics_service.track(
                db,
                e.name,
                user_id=p.user_id,
                anonymous_id=body.anonymous_id,
                source="web",
                properties=e.properties,
                occurred_at=e.occurred_at or datetime.now(UTC),
                client=True,
            )
        )
    await db.commit()
    return Envelope(data={"accepted": accepted})
