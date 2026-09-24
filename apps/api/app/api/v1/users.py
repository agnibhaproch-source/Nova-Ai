"""/api/v1/users/me* (docs/31 §3). Session auth only."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models_registry import get_registry
from app.api.deps import (
    Principal,
    clear_session_cookies,
    client_ip,
    rate_limit,
    request_id,
    require_csrf,
    require_user,
)
from app.core.errors import AppError, ErrorCode
from app.db.session import get_db
from app.schemas.common import Envelope, ListEnvelope
from app.schemas.users import (
    ChangePasswordIn,
    DeleteAccountIn,
    OnboardingIn,
    PreferencesOut,
    PreferencesPatchIn,
    UserOut,
    UserPatchIn,
    UserSessionOut,
)
from app.services import auth_service, session_service, user_service
from app.services.auth_service import ClientCtx

router = APIRouter(prefix="/users/me", tags=["users"])


async def session_only(p: Principal = Depends(require_user)) -> Principal:
    if p.auth_method != "session":
        raise AppError(ErrorCode.FORBIDDEN)
    return p


async def session_csrf(p: Principal = Depends(require_csrf)) -> Principal:
    if p.auth_method != "session":
        raise AppError(ErrorCode.FORBIDDEN)
    return p


@router.get("", operation_id="users_me", dependencies=[Depends(rate_limit("api_read"))])
async def me(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(session_only)
) -> Envelope[UserOut]:
    return Envelope(data=UserOut.from_domain(await user_service.get_user(db, p.uid)))


@router.patch("", operation_id="users_update", dependencies=[Depends(rate_limit("api_write"))])
async def update_me(
    body: UserPatchIn, db: AsyncSession = Depends(get_db), p: Principal = Depends(session_csrf)
) -> Envelope[UserOut]:
    user = await user_service.update_profile(db, p.uid, body.model_dump(exclude_unset=True))
    return Envelope(data=UserOut.from_domain(user))


@router.get(
    "/preferences",
    operation_id="users_preferences_get",
    dependencies=[Depends(rate_limit("api_read"))],
)
async def get_prefs(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(session_only)
) -> Envelope[PreferencesOut]:
    return Envelope(data=PreferencesOut.from_domain(await user_service.get_preferences(db, p.uid)))


@router.patch(
    "/preferences",
    operation_id="users_preferences_update",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def patch_prefs(
    body: PreferencesPatchIn,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(session_csrf),
) -> Envelope[PreferencesOut]:
    fields = body.model_dump(exclude_unset=True)
    allowed: set[str] = set()
    if fields.get("default_model_key") is not None:
        allowed = {m.key for m in get_registry().list_for_plan(p.plan_key)}
    prefs = await user_service.update_preferences(db, p.uid, fields, allowed_models=allowed)
    return Envelope(data=PreferencesOut.from_domain(prefs))


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="users_password",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(session_csrf),
) -> Response:
    ctx = ClientCtx(client_ip(request), request.headers.get("user-agent"), request_id(request))
    await auth_service.change_password(
        db, p.uid, p.session_id or "", body.current_password, body.new_password, ctx
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/onboarding/complete",
    operation_id="users_onboarding_complete",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def onboarding(
    body: OnboardingIn, db: AsyncSession = Depends(get_db), p: Principal = Depends(session_csrf)
) -> Envelope[UserOut]:
    user = await user_service.complete_onboarding(db, p.uid, body.model_dump(exclude_unset=True))
    return Envelope(data=UserOut.from_domain(user))


@router.get(
    "/sessions", operation_id="users_sessions_list", dependencies=[Depends(rate_limit("api_read"))]
)
async def list_sessions(
    db: AsyncSession = Depends(get_db), p: Principal = Depends(session_only)
) -> ListEnvelope[UserSessionOut]:
    rows = await session_service.list_active(db, p.uid)
    return ListEnvelope(data=[UserSessionOut.from_domain(s, p.session_id) for s in rows])


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="users_sessions_revoke",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(session_csrf),
) -> Response:
    await user_service.revoke_session(db, p.uid, session_id, request_id(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/revoke-others",
    operation_id="users_sessions_revoke_others",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def revoke_others(
    request: Request, db: AsyncSession = Depends(get_db), p: Principal = Depends(session_csrf)
) -> Envelope[dict[str, int]]:
    n = await user_service.revoke_other_sessions(db, p.uid, p.session_id or "", request_id(request))
    return Envelope(data={"revoked_count": n})


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="users_delete",
    dependencies=[Depends(rate_limit("api_write"))],
)
async def delete_me(
    body: DeleteAccountIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(session_csrf),
) -> Response:
    await user_service.delete_account(
        db, p.uid, body.password, body.confirmation, request_id(request)
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_session_cookies(response)
    return response
