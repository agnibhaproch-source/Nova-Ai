"""Shared fixtures: real Postgres (nova_test) + Redis db 15, security headers enforced."""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
_db_url = os.environ.get("DATABASE_URL", "")
if not _db_url.endswith("/nova_test"):
    # Derive the test DB from the dev .env (host/port) and force the nova_test database.
    from dotenv import dotenv_values  # provided by pydantic-settings

    env = dotenv_values(API_DIR.parents[1] / ".env")
    base = env.get("DATABASE_URL") or "postgresql+asyncpg://nova:nova@localhost:5432/nova"
    os.environ["DATABASE_URL"] = base.rsplit("/", 1)[0] + "/nova_test"
    redis = env.get("REDIS_URL") or "redis://localhost:6379/0"
    os.environ["REDIS_URL"] = redis.rsplit("/", 1)[0] + "/15"
os.environ.update(
    {
        "APP_ENV": "test",
        "APP_URL": "http://localhost:3000",
        "API_PROXY_SHARED_SECRET": "test-proxy-secret-" + "x" * 32,
        "AUTH_SECRET": "test-auth-secret-" + "y" * 32,
        "MODEL_REGISTRY_PATH": str(API_DIR / "tests" / "fixtures" / "models.test.yaml"),
        "GROQ_KEY_MODE": "server",  # BYOK behaviour is covered in tests/test_byok.py
        "GROQ_API_KEY": "gsk_test_key_not_real_0000000000",
        "GROQ_DEFAULT_MODEL": "test-model-primary",
        "GROQ_FAST_MODEL": "test-model-fast",
        "LOG_LEVEL": "warning",
        "SANDBOX_RUNNER_URL": "",  # tools default off; tests enable them explicitly
        "WEB_SEARCH_PROVIDER": "none",
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402

ORIGIN = "http://localhost:3000"
PROXY_HEADERS = {"x-nova-proxy-secret": "test-proxy-secret-" + "x" * 32, "origin": ORIGIN}
TABLES = [
    "payment_webhook_events",
    "payments",
    "subscriptions",
    "api_keys",
    "tool_calls",
    "memories",
    "data_exports",
    "moderation_flags",
    "document_chunks",
    "conversation_files",
    "files",
    "analytics_events",
    "audit_logs",
    "feedback",
    "message_parts",
    "usage_records",
    "usage_daily",
    "messages",
    "conversations",
    "email_tokens",
    "sessions",
    "user_preferences",
    "system_settings",
    "users",
]
PASSWORD = "correct-horse-battery-9"


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> None:
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        check=True,
        env={**os.environ},
        capture_output=True,
    )


@pytest.fixture(scope="session")
async def app():  # type: ignore[no-untyped-def]
    from app.core.logging import configure_logging
    from app.main import _init_models, create_app

    configure_logging()
    _init_models()
    application = create_app()
    yield application
    await get_redis().aclose()


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    async with get_sessionmaker()() as s:
        await s.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        await s.commit()
    await get_redis().flushdb()
    yield


class Client(httpx.AsyncClient):
    """Test client that mimics the Next.js proxy + browser CSRF behaviour."""

    def csrf(self) -> dict[str, str]:
        return {"x-csrf-token": self.cookies.get("nova_csrf") or ""}

    async def post_c(self, url: str, **kw):  # type: ignore[no-untyped-def]
        return await self.post(url, headers={**self.csrf(), **kw.pop("headers", {})}, **kw)

    async def patch_c(self, url: str, **kw):  # type: ignore[no-untyped-def]
        return await self.patch(url, headers={**self.csrf(), **kw.pop("headers", {})}, **kw)

    async def put_c(self, url: str, **kw):  # type: ignore[no-untyped-def]
        return await self.put(url, headers={**self.csrf(), **kw.pop("headers", {})}, **kw)

    async def delete_c(self, url: str, **kw):  # type: ignore[no-untyped-def]
        headers = {**self.csrf(), **kw.pop("headers", {})}
        if "json" in kw:
            return await self.request("DELETE", url, headers=headers, **kw)
        return await self.delete(url, headers=headers, **kw)


def make_client(app) -> Client:  # type: ignore[no-untyped-def]
    return Client(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers=PROXY_HEADERS
    )


@pytest.fixture
async def client(app) -> AsyncIterator[Client]:  # type: ignore[no-untyped-def]
    async with make_client(app) as c:
        yield c


async def signup(c: Client, email: str = "priya@example.com", name: str = "Priya") -> dict:
    r = await c.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "display_name": name, "accept_terms": True},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


@pytest.fixture
async def user_client(app) -> AsyncIterator[Client]:  # type: ignore[no-untyped-def]
    async with make_client(app) as c:
        await signup(c)
        yield c


def settings():  # type: ignore[no-untyped-def]
    return get_settings()
