"""Auth, user, preferences and session schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import available_timezones

from pydantic import EmailStr, Field, field_validator

from app.models import Session, User, UserPreferences
from app.schemas.common import In, Out


class UserOut(Out):
    id: uuid.UUID
    email: str
    display_name: str
    avatar_url: str | None = None
    role: str
    plan_key: str
    onboarding_completed: bool
    created_at: datetime

    @classmethod
    def from_domain(cls, u: User) -> UserOut:
        return cls(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            avatar_url=None,
            role=u.role,
            plan_key=u.plan_key,
            onboarding_completed=u.onboarding_completed_at is not None,
            created_at=u.created_at,
        )


class SignupIn(In):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=80)
    accept_terms: Literal[True]


class LoginIn(In):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenIn(In):
    token: str = Field(min_length=10, max_length=200)


class ForgotIn(In):
    email: EmailStr


class ResetIn(In):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=1, max_length=256)


class ChangePasswordIn(In):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class SessionOut(Out):
    id: uuid.UUID
    expires_at: datetime


class AuthSessionOut(Out):
    user: UserOut
    session: SessionOut


class UserPatchIn(In):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def _no_control(cls, v: str | None) -> str | None:
        if v is not None and any(ord(c) < 32 for c in v):
            raise ValueError("must not contain control characters")
        return v


class PreferencesOut(Out):
    theme: str
    default_model_key: str | None
    custom_instructions: str | None
    about_user: str | None
    memory_enabled: bool
    web_search_enabled: bool
    code_execution_enabled: bool
    send_with_enter: bool
    locale: str
    timezone: str
    tts_voice: str | None
    analytics_opt_out: bool

    @classmethod
    def from_domain(cls, p: UserPreferences) -> PreferencesOut:
        return cls.model_validate(p)


class PreferencesPatchIn(In):
    theme: Literal["system", "light", "dark"] | None = None
    default_model_key: str | None = None
    custom_instructions: str | None = Field(default=None, max_length=1500)
    about_user: str | None = Field(default=None, max_length=1500)
    memory_enabled: bool | None = None
    web_search_enabled: bool | None = None
    code_execution_enabled: bool | None = None
    send_with_enter: bool | None = None
    locale: Literal["en"] | None = None
    timezone: str | None = None
    tts_voice: str | None = Field(default=None, max_length=64)
    analytics_opt_out: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is not None and v not in available_timezones():
            raise ValueError("unknown timezone")
        return v


class OnboardingIn(In):
    custom_instructions: str | None = Field(default=None, max_length=1500)
    memory_enabled: bool | None = None


class UserSessionOut(Out):
    id: uuid.UUID
    device_label: str | None
    ip_address: str | None
    created_at: datetime
    last_seen_at: datetime
    is_current: bool = False

    @classmethod
    def from_domain(cls, s: Session, current: str | None) -> UserSessionOut:
        return cls(
            id=s.id,
            device_label=s.device_label,
            ip_address=str(s.ip_address) if s.ip_address else None,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            is_current=str(s.id) == current,
        )


class DeleteAccountIn(In):
    password: str = Field(min_length=1, max_length=256)
    confirmation: str
