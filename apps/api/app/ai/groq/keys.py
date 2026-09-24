"""User-supplied Groq API keys (BYOK), one per conversation (docs/14 §2a).

The key travels browser → Next.js BFF → FastAPI once, is validated against Groq, then kept
AES-GCM-encrypted in Redis under the conversation id with a sliding TTL. It is never written to
Postgres, never logged and never returned to the browser. The browser still never calls Groq.
"""

from __future__ import annotations

import base64
import contextlib
import contextvars
import hashlib
import os
import uuid
from collections.abc import Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.redis import get_redis, rkey

_current: contextvars.ContextVar[str | None] = contextvars.ContextVar("groq_key", default=None)


def current() -> str | None:
    return _current.get()


@contextlib.contextmanager
def using(key: str | None) -> Iterator[None]:
    token = _current.set(key)
    try:
        yield
    finally:
        _current.reset(token)


def set_current(key: str | None) -> None:
    """For task entrypoints (generation runner) that own their whole context."""
    _current.set(key)


def user_mode() -> bool:
    return get_settings().GROQ_KEY_MODE == "user"


def looks_valid(key: str) -> bool:
    return key.startswith("gsk_") and 20 <= len(key) <= 200 and key.isascii() and " " not in key


def _aead() -> AESGCM:
    secret = get_settings().AUTH_SECRET.get_secret_value().encode()
    return AESGCM(hashlib.sha256(b"nova-groq-key:" + secret).digest())


def _key(conversation_id: uuid.UUID) -> str:
    return rkey("groqkey", str(conversation_id))


def _ttl() -> int:
    return int(get_settings().GROQ_USER_KEY_TTL_HOURS * 3600)


async def save(conversation_id: uuid.UUID, api_key: str) -> None:
    nonce = os.urandom(12)
    blob = nonce + _aead().encrypt(nonce, api_key.encode(), str(conversation_id).encode())
    await get_redis().set(_key(conversation_id), base64.b64encode(blob), ex=_ttl())


async def load(conversation_id: uuid.UUID) -> str | None:
    raw = await get_redis().get(_key(conversation_id))
    if not raw:
        return None
    blob = base64.b64decode(raw)
    try:
        key = _aead().decrypt(blob[:12], blob[12:], str(conversation_id).encode()).decode()
    except Exception:
        return None
    await get_redis().expire(_key(conversation_id), _ttl())  # sliding: active chats stay usable
    return key


async def ttl_seconds(conversation_id: uuid.UUID) -> int | None:
    t = int(await get_redis().ttl(_key(conversation_id)))
    return t if t > 0 else None


async def delete(conversation_id: uuid.UUID) -> None:
    await get_redis().delete(_key(conversation_id))


async def for_conversation(conversation_id: uuid.UUID) -> str | None:
    """Key to use for this conversation: the user's in BYOK mode, else the server key (None)."""
    if not user_mode():
        return None
    key = await load(conversation_id)
    if key is None:
        raise AppError(ErrorCode.GROQ_KEY_REQUIRED)
    return key


async def verify(api_key: str) -> None:
    """Checks the key with a cheap authenticated call (GET /models). Raises GROQ_KEY_INVALID."""
    if not looks_valid(api_key):
        raise AppError(ErrorCode.GROQ_KEY_INVALID)
    from app.ai.groq.errors import ProviderError
    from app.ai.groq.provider import GroqProvider

    with using(api_key):
        try:
            await GroqProvider().list_models()
        except ProviderError as e:
            if e.code == ErrorCode.GROQ_KEY_INVALID:
                raise AppError(ErrorCode.GROQ_KEY_INVALID) from e
            raise AppError(ErrorCode.PROVIDER_UNAVAILABLE) from e
