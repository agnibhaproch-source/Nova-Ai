"""Phase 1: auth, sessions, CSRF, lockout, account, admin (docs/09, 10, 36)."""

from __future__ import annotations

from sqlalchemy import select, update

from app.db.session import get_sessionmaker
from app.models import AuditLog, User
from tests.conftest import PASSWORD, Client, make_client, signup


async def test_healthz_is_public_but_api_requires_proxy_secret(app) -> None:
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as raw:
        assert (await raw.get("/healthz")).status_code == 200
        r = await raw.get("/api/v1/app-config")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_signup_sets_cookies_and_session(client: Client) -> None:
    user = await signup(client)
    assert user["email"] == "priya@example.com" and user["plan_key"] == "free"
    assert "email_verified" not in user  # no email verification step (removed by product decision)
    assert client.cookies.get("nova_session") and client.cookies.get("nova_csrf")
    r = await client.get("/api/v1/auth/session")
    assert r.status_code == 200
    assert r.json()["data"]["user"]["display_name"] == "Priya"


async def test_signup_rejects_weak_password_duplicate_and_bad_origin(client: Client) -> None:
    body = {
        "email": "a@example.com",
        "password": "short",
        "display_name": "A",
        "accept_terms": True,
    }
    r = await client.post("/api/v1/auth/signup", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "PASSWORD_POLICY"
    await signup(client, "dup@example.com")
    r = await client.post(
        "/api/v1/auth/signup", json={**body, "email": "DUP@example.com", "password": PASSWORD}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"
    r = await client.post(
        "/api/v1/auth/signup",
        json={**body, "password": PASSWORD},
        headers={"origin": "https://evil.example"},
    )
    assert r.json()["error"]["code"] == "CSRF_FAILED"


async def test_login_logout_and_generic_errors(app) -> None:
    async with make_client(app) as c:
        await signup(c)
    async with make_client(app) as c:
        r = await c.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
        )
        assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
        r = await c.post(
            "/api/v1/auth/login", json={"email": "Priya@Example.com", "password": PASSWORD}
        )
        assert r.status_code == 200
        assert (await c.get("/api/v1/users/me")).status_code == 200
        r = await c.post("/api/v1/auth/logout")  # missing CSRF header
        assert r.json()["error"]["code"] == "CSRF_FAILED"
        assert (await c.post_c("/api/v1/auth/logout")).status_code == 204
        assert (await c.get("/api/v1/users/me")).status_code == 401


async def test_revoked_session_is_rejected_immediately(app) -> None:
    async with make_client(app) as c:
        await signup(c)
        token = c.cookies.get("nova_session")
        assert (await c.get("/api/v1/users/me")).status_code == 200  # warms Redis cache
        await c.post_c("/api/v1/auth/logout")
        c.cookies.set("nova_session", token)
        assert (await c.get("/api/v1/users/me")).status_code == 401


async def test_lockout_after_repeated_failures(app) -> None:
    async with make_client(app) as c:
        await signup(c)
    async with make_client(app) as c:
        codes = []
        for _ in range(10):
            r = await c.post(
                "/api/v1/auth/login",
                json={"email": "priya@example.com", "password": "wrong-password-123"},
            )
            codes.append(r.json()["error"]["code"])
        assert set(codes) <= {"INVALID_CREDENTIALS", "RATE_LIMITED"}
        r = await c.post(
            "/api/v1/auth/login", json={"email": "priya@example.com", "password": PASSWORD}
        )
        assert r.json()["error"]["code"] in ("ACCOUNT_LOCKED", "RATE_LIMITED")


async def test_verify_email_endpoints_are_gone(user_client: Client) -> None:
    r = await user_client.post("/api/v1/auth/verify-email", json={"token": "x" * 43})
    assert r.status_code in (404, 405)


async def test_password_change_revokes_other_sessions(app) -> None:
    async with make_client(app) as a, make_client(app) as b:
        await signup(a)
        await b.post(
            "/api/v1/auth/login", json={"email": "priya@example.com", "password": PASSWORD}
        )
        assert (await b.get("/api/v1/users/me")).status_code == 200
        r = await a.post_c(
            "/api/v1/users/me/password",
            json={"current_password": PASSWORD, "new_password": "another-strong-pass-7"},
        )
        assert r.status_code == 204
        assert (await a.get("/api/v1/users/me")).status_code == 200
        assert (await b.get("/api/v1/users/me")).status_code == 401


async def test_preferences_and_sessions(user_client: Client) -> None:
    r = await user_client.patch_c(
        "/api/v1/users/me/preferences",
        json={"theme": "dark", "custom_instructions": "Be concise.", "timezone": "Asia/Kolkata"},
    )
    assert r.status_code == 200 and r.json()["data"]["theme"] == "dark"
    r = await user_client.patch_c("/api/v1/users/me/preferences", json={"timezone": "Mars/Base"})
    assert r.status_code == 422
    r = await user_client.patch_c("/api/v1/users/me/preferences", json={"unknown": 1})
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    r = await user_client.get("/api/v1/users/me/sessions")
    assert len(r.json()["data"]) == 1 and r.json()["data"][0]["is_current"]


async def test_delete_account(user_client: Client) -> None:
    r = await user_client.delete_c(
        "/api/v1/users/me", json={"password": PASSWORD, "confirmation": "nope"}
    )
    assert r.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    r = await user_client.delete_c(
        "/api/v1/users/me", json={"password": PASSWORD, "confirmation": "DELETE"}
    )
    assert r.status_code == 204
    assert (await user_client.get("/api/v1/users/me")).status_code == 401


async def test_admin_requires_role_and_audits(app) -> None:
    async with make_client(app) as admin_c, make_client(app) as user_c:
        await signup(admin_c, "admin@example.com", "Admin")
        target = await signup(user_c, "user@example.com", "User")
        async with get_sessionmaker()() as s:
            await s.execute(
                update(User).where(User.email == "admin@example.com").values(role="admin")
            )
            await s.commit()
        await admin_c.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
        )
        r = await user_c.get("/api/v1/admin/users")
        assert r.status_code == 403
        r = await admin_c.get("/api/v1/admin/users")
        assert r.status_code == 200 and r.json()["meta"]["total"] == 2
        r = await admin_c.patch_c(
            f"/api/v1/admin/users/{target['id']}",
            json={"status": "suspended", "reason": "abuse report #1"},
        )
        assert r.status_code == 200 and r.json()["data"]["status"] == "suspended"
        assert (await user_c.get("/api/v1/users/me")).status_code == 401
        async with get_sessionmaker()() as s:
            actions = set((await s.execute(select(AuditLog.action))).scalars())
        assert "admin.user.suspended" in actions


async def test_unhandled_errors_do_not_leak(client: Client) -> None:
    r = await client.get("/api/v1/does-not-exist")
    body = r.json()
    assert r.status_code == 404 and set(body["error"]) >= {"code", "message", "request_id"}
    assert "Traceback" not in r.text
