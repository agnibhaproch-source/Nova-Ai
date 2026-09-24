"""/api/v1/auth/* (docs/31 §2)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CSRF_COOKIE,
    Principal,
    clear_session_cookies,
    client_ip,
    get_principal,
    rate_limit,
    request_id,
    require_csrf,
    require_origin,
    set_session_cookies,
)
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.security import csrf_token_for, sha256
from app.db.session import get_db
from app.models import Session as SessionModel
from app.ratelimit import limiter
from app.schemas.common import Envelope
from app.schemas.users import (
    AuthSessionOut,
    ForgotIn,
    LoginIn,
    ResetIn,
    SessionOut,
    SignupIn,
    UserOut,
)
from app.services import auth_service, user_service
from app.services.auth_service import ClientCtx

router = APIRouter(prefix="/auth", tags=["auth"])


def _ctx(request: Request) -> ClientCtx:
    return ClientCtx(
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
        request_id=request_id(request),
    )


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    operation_id="auth_signup",
    dependencies=[Depends(require_origin), Depends(rate_limit("auth_signup"))],
)
async def signup(
    body: SignupIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> Envelope[UserOut]:
    res = await auth_service.signup(
        db, str(body.email), body.password, body.display_name, _ctx(request)
    )
    set_session_cookies(response, res.token, str(res.session.id))
    return Envelope(data=UserOut.from_domain(res.user))


@router.post(
    "/login",
    operation_id="auth_login",
    dependencies=[Depends(require_origin), Depends(rate_limit("auth_login_ip"))],
)
async def login(
    body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> Envelope[UserOut]:
    await limiter.enforce("auth_login_email", sha256(str(body.email).lower()).hex())
    res = await auth_service.login(db, str(body.email), body.password, _ctx(request))
    set_session_cookies(response, res.token, str(res.session.id))
    return Envelope(data=UserOut.from_domain(res.user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, operation_id="auth_logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
) -> Response:
    await auth_service.logout(db, p.session_id or "", p.uid, _ctx(request))
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_session_cookies(response)
    return response


@router.get("/session", operation_id="auth_session")
async def session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(get_principal),
) -> Envelope[AuthSessionOut]:
    if not p.is_authenticated:
        clear_session_cookies(response)
        raise AppError(ErrorCode.AUTH_REQUIRED)
    user = await user_service.get_user(db, p.uid)
    if request.cookies.get(CSRF_COOKIE) != csrf_token_for(p.session_id or ""):
        s = get_settings()
        response.set_cookie(
            CSRF_COOKIE,
            csrf_token_for(p.session_id or ""),
            httponly=False,
            secure=s.cookie_secure,
            samesite="lax",
            path="/",
            max_age=s.SESSION_TTL_DAYS * 86400,
            domain=s.COOKIE_DOMAIN,
        )
    sess = await db.get(SessionModel, uuid.UUID(p.session_id))
    assert sess is not None
    return Envelope(
        data=AuthSessionOut(
            user=UserOut.from_domain(user),
            session=SessionOut(id=sess.id, expires_at=sess.expires_at),
        )
    )


@router.post(
    "/password/forgot",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="auth_password_forgot",
    dependencies=[Depends(require_origin), Depends(rate_limit("auth_password_forgot_ip"))],
)
async def forgot(
    body: ForgotIn, request: Request, db: AsyncSession = Depends(get_db)
) -> Envelope[dict[str, bool]]:
    await limiter.enforce("auth_password_forgot_email", sha256(str(body.email).lower()).hex())
    await auth_service.forgot_password(db, str(body.email), _ctx(request))
    return Envelope(data={"accepted": True})


@router.post(
    "/password/reset",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="auth_password_reset",
    dependencies=[Depends(require_origin)],
)
async def reset(body: ResetIn, request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    await auth_service.reset_password(db, body.token, body.new_password, _ctx(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
