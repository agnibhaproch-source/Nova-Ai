"""Password hashing, token generation and HMAC helpers (docs/09_AUTHENTICATION.md)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import unicodedata
from functools import lru_cache
from pathlib import Path

import anyio
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

_ph = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)
_DATA = Path(__file__).parent / "data"


@lru_cache
def _dummy_hash() -> str:
    return _ph.hash("nova-dummy-password-for-timing")


@lru_cache
def common_passwords() -> frozenset[str]:
    path = _DATA / "common_passwords.txt"
    if not path.exists():
        return frozenset()
    return frozenset(line.strip().lower() for line in path.read_text().splitlines() if line.strip())


def normalize_password(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def password_policy_violation(password: str, email: str) -> str | None:
    pw = normalize_password(password)
    if len(pw) < 12 or len(pw) > 128:
        return "Password must be 12–128 characters."
    if pw.lower() in common_passwords():
        return "This password is too common."
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in pw.lower():
        return "Password must not contain your email name."
    return None


async def hash_password(password: str) -> str:
    return await anyio.to_thread.run_sync(_ph.hash, normalize_password(password))


async def verify_password(password: str, encoded: str | None) -> bool:
    """Constant-work verification; verifies against a dummy hash when the user doesn't exist."""

    def _verify() -> bool:
        try:
            return _ph.verify(encoded or _dummy_hash(), normalize_password(password)) and bool(
                encoded
            )
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    return await anyio.to_thread.run_sync(_verify)


def needs_rehash(encoded: str) -> bool:
    return _ph.check_needs_rehash(encoded)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def sha256(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def hmac_sha256(message: str, *, key: str | None = None) -> bytes:
    secret = key or get_settings().AUTH_SECRET.get_secret_value()
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def csrf_token_for(session_id: str) -> str:
    return b64url(hmac_sha256(f"csrf:{session_id}"))


def constant_time_eq(a: str | bytes, b: str | bytes) -> bool:
    a_b = a.encode() if isinstance(a, str) else a
    b_b = b.encode() if isinstance(b, str) else b
    return hmac.compare_digest(a_b, b_b)


def end_user_hash(user_id: str) -> str:
    """Opaque per-user identifier sent to Groq (PRV-008)."""
    return hmac_sha256(f"groq-user:{user_id}").hex()[:32]


_B62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def new_api_key() -> str:
    return "nova_sk_" + "".join(secrets.choice(_B62) for _ in range(40))
