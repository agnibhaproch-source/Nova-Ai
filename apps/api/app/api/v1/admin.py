"""/api/v1/admin/* — server-side role checks + audit on every mutation (docs/36)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, rate_limit, request_id, require_csrf, require_role
from app.core.errors import AppError, ErrorCode, not_found
from app.db.session import get_db
from app.models import AuditLog, Session, User
from app.schemas.common import Envelope, In, ListEnvelope, Out
from app.services import session_service, settings_service, user_service
from app.services.audit_service import audit

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(rate_limit("admin"))])
support = require_role("support")
admin = require_role("admin")


def _mask(email: str, role: str) -> str:
    if role == "admin":
        return email
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


class AdminUserOut(Out):
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    status: str
    plan_key: str
    created_at: datetime
    last_login_at: datetime | None
    suspended_reason: str | None


def _user_out(u: User, viewer_role: str) -> AdminUserOut:
    return AdminUserOut(
        id=u.id,
        email=_mask(u.email, viewer_role),
        display_name=u.display_name,
        role=u.role,
        status=u.status,
        plan_key=u.plan_key,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
        suspended_reason=u.suspended_reason,
    )


@router.get("/users", operation_id="admin_users_list")
async def list_users(
    q: str | None = Query(default=None, max_length=200),
    status: Literal["active", "suspended"] | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(support),
) -> ListEnvelope[AdminUserOut]:
    rows, total = await user_service.list_users_admin(
        db, q=q, status=status, page=page, page_size=page_size
    )
    return ListEnvelope(
        data=[_user_out(u, p.role) for u in rows],
        meta={"total": total, "page": page, "page_size": page_size},
    )


@router.get("/users/{user_id}", operation_id="admin_users_get")
async def get_user(
    user_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(support),
) -> Envelope[AdminUserOut]:
    u = await db.get(User, user_id)
    if u is None or u.status == "deleted":
        raise not_found()
    sessions = await db.scalar(
        select(func.count()).where(Session.user_id == u.id, Session.revoked_at.is_(None))
    )
    audit(
        db,
        "admin.user.viewed",
        actor_user_id=p.uid,
        actor_type=p.role,
        target_type="user",
        target_id=u.id,
        request_id=request_id(request),
    )
    await db.commit()
    out = _user_out(u, "admin")
    return Envelope(data=out, meta={"active_sessions": sessions or 0})


class AdminUserPatchIn(In):
    status: Literal["active", "suspended"] | None = None
    suspended_reason: str | None = Field(default=None, max_length=500)
    role: Literal["user", "support", "admin"] | None = None
    plan_key_override: Literal["free", "plus", "pro"] | None = None
    reason: str = Field(min_length=3, max_length=500)


@router.patch("/users/{user_id}", operation_id="admin_users_update")
async def update_user(
    user_id: uuid.UUID,
    body: AdminUserPatchIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _a: Principal = Depends(admin),
) -> Envelope[AdminUserOut]:
    fields: dict[str, Any] = body.model_dump(exclude_unset=True, exclude={"reason"})
    if "plan_key_override" in fields:
        fields["plan_key"] = fields.pop("plan_key_override")
    u = await user_service.admin_update_user(
        db, p.uid, user_id, fields, body.reason, request_id(request)
    )
    return Envelope(data=_user_out(u, "admin"))


class ReasonIn(In):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/users/{user_id}/revoke-sessions", operation_id="admin_users_revoke_sessions")
async def revoke_sessions(
    user_id: uuid.UUID,
    body: ReasonIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _a: Principal = Depends(admin),
) -> Envelope[dict[str, int]]:
    if await db.get(User, user_id) is None:
        raise not_found()
    n = await session_service.revoke_all_for_user(db, user_id, "admin_revoked")
    audit(
        db,
        "admin.user.sessions_revoked",
        actor_user_id=p.uid,
        actor_type="admin",
        target_type="user",
        target_id=user_id,
        reason=body.reason,
        request_id=request_id(request),
        metadata={"revoked_count": n},
    )
    await db.commit()
    return Envelope(data={"revoked_count": n})


class AuditOut(Out):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_type: str
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    reason: str | None
    request_id: str | None
    metadata: dict[str, Any]
    created_at: datetime


@router.get("/audit-logs", operation_id="admin_audit_logs")
async def audit_logs(
    action: str | None = Query(default=None, max_length=64),
    actor_user_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _p: Principal = Depends(support),
) -> ListEnvelope[AuditOut]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if actor_user_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    rows = (await db.execute(stmt)).scalars().all()
    return ListEnvelope(
        data=[
            AuditOut(
                id=r.id,
                actor_user_id=r.actor_user_id,
                actor_type=r.actor_type,
                action=r.action,
                target_type=r.target_type,
                target_id=r.target_id,
                reason=r.reason,
                request_id=r.request_id,
                metadata=r.metadata_,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


@router.get("/settings", operation_id="admin_settings_get")
async def get_settings_(
    db: AsyncSession = Depends(get_db), _p: Principal = Depends(admin)
) -> Envelope[list[dict[str, Any]]]:
    values = await settings_service.get_all(db)
    return Envelope(
        data=[
            {"key": k, "value": values[k], "description": d.description}
            for k, d in settings_service.REGISTRY.items()
        ]
    )


class SettingIn(In):
    value: Any
    reason: str = Field(min_length=3, max_length=500)


@router.patch("/settings/{key}", operation_id="admin_settings_update")
async def update_setting(
    key: str,
    body: SettingIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    p: Principal = Depends(require_csrf),
    _a: Principal = Depends(admin),
) -> Envelope[dict[str, Any]]:
    value = await settings_service.set_value(db, key, body.value, p.uid)
    audit(
        db,
        "admin.settings.updated",
        actor_user_id=p.uid,
        actor_type="admin",
        reason=body.reason,
        request_id=request_id(request),
        metadata={"key": key},
    )
    await db.commit()
    return Envelope(data={"key": key, "value": value})


__all__ = ["AppError", "ErrorCode", "router"]
