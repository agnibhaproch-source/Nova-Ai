"""Voice: STT/TTS via replaceable providers; v1 adapters use Groq (docs/26)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import magic
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.groq.service import get_groq_service
from app.ai.provider import CallContext
from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.redis import get_redis, rkey
from app.services import quota_service
from app.services.usage_service import record as record_usage

MAX_AUDIO_BYTES = 25 * 1024 * 1024
AUDIO_TYPES = ("audio/", "video/webm")


def _server_key() -> bool:
    # Voice calls aren't tied to a conversation, so they need the server-held key.
    s = get_settings()
    return s.GROQ_KEY_MODE == "server" and s.GROQ_API_KEY is not None


def stt_enabled() -> bool:
    s = get_settings()
    return _server_key() and bool(s.GROQ_STT_MODEL) and (s.VOICE_STT_PROVIDER or "groq") == "groq"


def tts_mode() -> str:
    """'groq' (server synthesis), 'browser' (on-device Web Speech API) or 'none'."""
    s = get_settings()
    if s.VOICE_TTS_PROVIDER == "none":
        return "none"
    if (
        _server_key()
        and s.GROQ_TTS_MODEL
        and s.GROQ_TTS_DEFAULT_VOICE
        and (s.VOICE_TTS_PROVIDER or "groq") == "groq"
    ):
        return "groq"
    return "browser"


def voices() -> list[str]:
    return [v.strip() for v in get_settings().GROQ_TTS_VOICES.split(",") if v.strip()]


async def _voice_quota(db: AsyncSession, user_id: uuid.UUID, plan_key: str, seconds: float) -> None:
    limits = await quota_service.plan_limits(db, plan_key)
    key = rkey("q", "vs", user_id, datetime.now(UTC).strftime("%Y%m%d"))
    try:
        used = float(await get_redis().incrbyfloat(key, seconds))
        await get_redis().expire(key, 48 * 3600)
    except Exception:
        return
    if used > float(limits.get("voice_minutes_per_day", 5)) * 60:
        raise AppError(ErrorCode.QUOTA_EXCEEDED, "You've used today's voice minutes.")


async def transcribe(
    db: AsyncSession,
    user_id: uuid.UUID,
    plan_key: str,
    audio: bytes,
    filename: str,
    language: str | None,
    request_id: str,
) -> dict[str, object]:
    if not stt_enabled():
        raise AppError(ErrorCode.VOICE_UNAVAILABLE)
    if len(audio) > MAX_AUDIO_BYTES:
        raise AppError(ErrorCode.AUDIO_TOO_LONG)
    detected = magic.from_buffer(audio[:4096], mime=True)
    if not detected.startswith(AUDIO_TYPES) and detected != "application/octet-stream":
        raise AppError(ErrorCode.UNSUPPORTED_FILE_TYPE)
    await _voice_quota(db, user_id, plan_key, 0)
    s = get_settings()
    assert s.GROQ_STT_MODEL
    res = await get_groq_service().transcribe(
        audio,
        filename or "audio.webm",
        model_id=s.GROQ_STT_MODEL,
        language=language,
        ctx=CallContext(request_id=request_id, user_id=user_id),
    )
    text = str(res.get("text") or "").strip()
    duration = res.get("duration_seconds")
    seconds = float(duration) if isinstance(duration, int | float) else len(audio) / 16000
    if seconds > 600:
        raise AppError(ErrorCode.AUDIO_TOO_LONG)
    await _voice_quota(db, user_id, plan_key, seconds)
    rec = record_usage(
        db, kind="stt", model=None, usage=None, request_id=request_id, user_id=user_id
    )
    rec.model_id, rec.audio_seconds = s.GROQ_STT_MODEL, Decimal(str(round(seconds, 2)))
    await db.commit()
    if not text:
        raise AppError(ErrorCode.NO_SPEECH_DETECTED)
    return {"text": text, "language": res.get("language"), "duration_seconds": round(seconds, 2)}


def speakable(markdown: str, limit: int = 4000) -> str:
    """Strip markdown for TTS: code omitted, links → domain, citations removed (docs/26 §4)."""
    t = re.sub(r"```.*?```", " (code omitted) ", markdown, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!?\[([^\]]*)\]\((https?://)?([^/)\s]+)[^)]*\)", r"\1 (\3)", t)
    t = re.sub(r"\[\d{1,2}(?:\s*,\s*\d{1,2})*\]", "", t)
    t = re.sub(r"[#*_>|~-]{1,3}", " ", t)
    return " ".join(t.split())[:limit]


async def synthesize(
    db: AsyncSession,
    user_id: uuid.UUID,
    plan_key: str,
    text: str,
    voice: str | None,
    request_id: str,
) -> bytes:
    if tts_mode() != "groq":
        raise AppError(ErrorCode.VOICE_UNAVAILABLE)
    s = get_settings()
    v = voice if voice in voices() else s.GROQ_TTS_DEFAULT_VOICE
    body = speakable(text)
    await _voice_quota(db, user_id, plan_key, len(body) / 15)
    assert s.GROQ_TTS_MODEL and v
    audio = await get_groq_service().synthesize(
        body,
        model_id=s.GROQ_TTS_MODEL,
        voice=v,
        fmt="mp3",
        ctx=CallContext(request_id=request_id, user_id=user_id),
    )
    rec = record_usage(
        db, kind="tts", model=None, usage=None, request_id=request_id, user_id=user_id
    )
    rec.model_id, rec.characters = s.GROQ_TTS_MODEL, len(body)
    await db.commit()
    return audio
