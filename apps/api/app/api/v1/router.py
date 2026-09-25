"""Aggregates all v1 routers."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    admin_ops,
    auth,
    conversations,
    features,
    files,
    messages,
    models,
    system,
    users,
)

api_router = APIRouter()
for module in (
    auth,
    users,
    system,
    conversations,
    messages,
    files,
    features,
    models,
    admin,
    admin_ops,
):
    api_router.include_router(module.router)
