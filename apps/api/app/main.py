"""FastAPI application factory (docs/05)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.models_registry import RegistryInvalid, init_registry
from app.api.deps import global_ip_limit, request_id
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import configure_logging
from app.core.redis import get_redis
from app.db.session import get_engine
from app.workers.queue import close_pool

log = structlog.get_logger()

CONSTRAINT_ERRORS = {"uq_users_email_active": ErrorCode.EMAIL_ALREADY_REGISTERED}


def _error_response(request: Request, err: AppError) -> JSONResponse:
    headers = {"Retry-After": str(err.retry_after)} if err.retry_after else None
    return JSONResponse(err.to_body(request_id(request)), status_code=err.status, headers=headers)


def _init_models() -> None:
    settings = get_settings()
    try:
        init_registry(settings.model_registry_file)
    except (RegistryInvalid, ValueError) as e:
        log.critical("startup.config_invalid", setting="models.yaml", reason=str(e))
        if settings.APP_ENV in ("staging", "production"):
            raise


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("nova-api")
    settings = get_settings()
    if settings.SENTRY_DSN:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT or settings.APP_ENV,
            release=settings.APP_VERSION,
            send_default_pii=False,
            traces_sample_rate=0,
        )
    _init_models()
    if (
        settings.APP_ENV != "test"
        and settings.GROQ_KEY_MODE == "server"
        and settings.GROQ_API_KEY is not None
    ):
        try:
            from app.ai.groq.service import get_groq_service
            from app.ai.models_registry import get_registry

            get_registry()
            report = await get_groq_service().verify_models()
            get_registry().validate_complete()
            log.info("model_registry.verified", report=report)
        except Exception as e:  # dev: keep serving non-chat features; prod: fail fast
            log.critical("startup.config_invalid", setting="models.yaml", reason=str(e))
            if settings.APP_ENV in ("staging", "production"):
                raise
            from app.ai.models_registry import set_registry

            set_registry(None)
    yield
    from app.streaming.runner import shutdown_generations

    await shutdown_generations()
    await close_pool()
    await get_redis().aclose()
    await get_engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="NOVA AI API",
        version=settings.APP_VERSION,
        lifespan=lifespan,
        openapi_url="/api/v1/openapi.json" if settings.APP_ENV != "production" else None,
        docs_url="/api/v1/docs" if settings.is_dev else None,
        redoc_url=None,
    )

    from app.core.middleware import RequestContextMiddleware

    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status >= 500:
            log.error("app.error", code=str(exc.code))
        return _error_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"field": ".".join(str(p) for p in e["loc"]), "issue": e["type"], "message": e["msg"]}
            for e in exc.errors()
        ]
        return _error_response(request, AppError(ErrorCode.VALIDATION_ERROR, details=details))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = (
            ErrorCode.METHOD_NOT_ALLOWED
            if exc.status_code == 405
            else (
                ErrorCode.PAYLOAD_TOO_LARGE
                if exc.status_code == 413
                else ErrorCode.RESOURCE_NOT_FOUND
            )
        )
        return _error_response(request, AppError(code))

    @app.exception_handler(IntegrityError)
    async def integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
        name = getattr(getattr(exc.orig, "__cause__", None), "constraint_name", None)
        code = CONSTRAINT_ERRORS.get(name or "", ErrorCode.CONFLICT)
        if code == ErrorCode.CONFLICT:
            log.error("db.integrity_error", constraint=name)
        return _error_response(request, AppError(code))

    @app.exception_handler(OperationalError)
    @app.exception_handler(DBAPIError)
    async def db_error(request: Request, exc: Exception) -> JSONResponse:
        log.error("db.error", error_type=type(exc).__name__)
        return _error_response(request, AppError(ErrorCode.DATABASE_ERROR))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("app.unhandled_exception", error_type=type(exc).__name__)
        return _error_response(request, AppError(ErrorCode.INTERNAL_ERROR))

    from app.api.v1.router import api_router
    from app.api.v1.system import health_router

    app.include_router(health_router)
    app.include_router(api_router, prefix="/api/v1", dependencies=[Depends(global_ip_limit)])
    return app


app = create_app()
