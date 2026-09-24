"""Request dependencies: principal resolution, CSRF, roles, rate limits (docs/09 §6, §10–11)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import structlog
from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import constant_time_eq, csrf_token_for
from app.db.session import get_db
from app.ratelimit import limiter
from app.services import session_service

SESSION_COOKIE = "nova_session"
CSRF_COOKIE = "nova_csrf"
ALL_SCOPES = frozenset(
    {
        "chat:write",
        "conversations:read",
        "conversations:write",
        "files:read",
        "files:write",
        "memories:read",
        "usage:read",
    }
)


@dataclass
class Principal:
    user_id: uuid.UUID | None = None
    role: str = "anonymous"
    plan_key: str = "free"
    created_at: str | None = None
    session_id: str | None = None
    api_key_id: uuid.UUID | None = None
    auth_method: str = "anonymous"
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None

    @property
    def uid(self) -> uuid.UUID:
        if self.user_id is None:
            raise AppError(ErrorCode.AUTH_REQUIRED)
        return self.user_id


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip() or None
    return request.client.host if request.client else None


def request_id(request: Request) -> str:
    return str(request.scope.get("state", {}).get("request_id", "-"))


async def get_principal(request: Request, db: AsyncSession = Depends(get_db)) -> Principal:
    cached: Principal | None = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    principal = Principal()
    auth = request.headers.get("authorization")
    if auth:
        scheme, _, secret = auth.partition(" ")
        if scheme.lower() != "bearer" or not secret.startswith("nova_sk_"):
            raise AppError(ErrorCode.AUTH_INVALID)
        from app.services import api_key_service

        info = await api_key_service.resolve(db, secret.strip(), client_ip(request))
        if info is None:
            await limiter.enforce("api_key_auth_fail", f"ip:{client_ip(request)}")
            raise AppError(ErrorCode.AUTH_INVALID)
        principal = Principal(
            user_id=uuid.UUID(info["user_id"]),
            role=info["role"],
            plan_key=info["plan_key"],
            created_at=info["created_at"],
            api_key_id=uuid.UUID(info["api_key_id"]),
            auth_method="api_key",
            scopes=frozenset(info["scopes"]),
        )
        structlog.contextvars.bind_contextvars(user_id=info["user_id"])
        request.state.principal = principal
        return principal
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        sess = await session_service.resolve(db, token)
        if sess and sess.status == "active":
            principal = Principal(
                user_id=uuid.UUID(sess.user_id),
                role=sess.role,
                plan_key=sess.plan_key,
                created_at=sess.created_at,
                session_id=sess.session_id,
                auth_method="session",
                scopes=ALL_SCOPES,
            )
            structlog.contextvars.bind_contextvars(user_id=sess.user_id)
    request.state.principal = principal
    return principal


async def require_user(p: Principal = Depends(get_principal)) -> Principal:
    if not p.is_authenticated:
        raise AppError(ErrorCode.AUTH_REQUIRED)
    return p


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer", "")
        origin = "/".join(referer.split("/")[:3]) if referer else None
    if origin != get_settings().app_origin:
        raise AppError(ErrorCode.CSRF_FAILED)


async def require_origin(request: Request) -> None:
    """For pre-session POSTs (login/signup/...): Origin must equal APP_URL (docs/09 §10.3)."""
    _check_origin(request)


async def require_csrf(request: Request, p: Principal = Depends(require_user)) -> Principal:
    if p.auth_method != "session":
        return p
    header = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    expected = csrf_token_for(p.session_id or "")
    if not (header and constant_time_eq(header, cookie) and constant_time_eq(header, expected)):
        structlog.get_logger().warning("security.csrf_failed", path=request.url.path)
        raise AppError(ErrorCode.CSRF_FAILED)
    _check_origin(request)
    return p


def require_role(*roles: str) -> Callable[..., Awaitable[Principal]]:
    allowed = set(roles) | {"admin"}

    async def dep(p: Principal = Depends(require_user)) -> Principal:
        if p.auth_method != "session":
            raise AppError(ErrorCode.FORBIDDEN)
        if p.role not in allowed:
            raise AppError(ErrorCode.FORBIDDEN)
        return p

    return dep


def require_scopes(*scopes: str) -> Callable[..., Awaitable[Principal]]:
    async def dep(p: Principal = Depends(require_user)) -> Principal:
        if not set(scopes) <= p.scopes:
            raise AppError(ErrorCode.INSUFFICIENT_SCOPE)
        return p

    return dep


def rate_limit(policy: str) -> Callable[..., Awaitable[None]]:
    async def dep(
        request: Request, response: Response, p: Principal = Depends(get_principal)
    ) -> None:
        ident = f"user:{p.user_id}" if p.user_id else f"ip:{client_ip(request)}"
        d = await limiter.enforce(policy, ident, plan=p.plan_key)
        response.headers["RateLimit-Limit"] = str(d.limit)
        response.headers["RateLimit-Remaining"] = str(max(0, d.remaining))
        response.headers["RateLimit-Reset"] = str(d.reset)

    return dep


async def global_ip_limit(request: Request) -> None:
    await limiter.enforce("global_ip", f"ip:{client_ip(request)}")


def set_session_cookies(response: Response, token: str, session_id: str) -> None:
    s = get_settings()
    max_age = s.SESSION_TTL_DAYS * 86400
    for name, value, http_only in (
        (SESSION_COOKIE, token, True),
        (CSRF_COOKIE, csrf_token_for(session_id), False),
    ):
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            path="/",
            secure=s.cookie_secure,
            samesite="lax",
            domain=s.COOKIE_DOMAIN,
            httponly=http_only,
        )


def clear_session_cookies(response: Response) -> None:
    s = get_settings()
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(
            name, path="/", domain=s.COOKIE_DOMAIN, secure=s.cookie_secure, samesite="lax"
        )
