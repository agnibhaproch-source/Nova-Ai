"""Phases 3–10: files + RAG, tools, memory, API keys, admin (docs/18–31)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select, update

from app.db.session import get_sessionmaker
from app.documents.chunker import chunk
from app.documents.extract import Segment
from app.models import DocumentChunk, File, User
from app.search.fetcher import BlockedURL, resolve_public, validate_url
from app.services import memory_service
from app.tools.base import ToolError
from app.tools.calculator import evaluate
from tests.conftest import Client, make_client, signup


async def set_user(**values: Any) -> None:
    async with get_sessionmaker()() as s:
        await s.execute(update(User).values(**values))
        await s.commit()


async def relogin(c: Client) -> None:
    """Session info is cached; a fresh login picks up plan/verification changes."""
    from app.services.auth_service import invalidate_user_sessions_cache

    async with get_sessionmaker()() as s:
        uid = await s.scalar(select(User.id))
    async with get_sessionmaker()() as s:
        await invalidate_user_sessions_cache(s, uid)


# ------------------------------------------------------------------ calculator
@pytest.mark.parametrize(
    ("expr", "want"),
    [
        ("2 + 3 * 4", Decimal(14)),
        ("sqrt(16)", 4),
        ("0.1 + 0.2", Decimal("0.3")),
        ("-(2**10)", -1024),
    ],
)
def test_calculator_evaluates(expr: str, want: Any) -> None:
    assert Decimal(str(evaluate(expr))) == Decimal(str(want))


@pytest.mark.parametrize(
    "expr",
    ["__import__('os').system('id')", "().__class__", "open('x')", "2 ** 100000", "[1,2]", "a.b"],
)
def test_calculator_rejects_unsafe(expr: str) -> None:
    with pytest.raises(ToolError):
        evaluate(expr)


# ------------------------------------------------------------------ SSRF guard
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:pw@example.com/",
        "http://example.com:6379/",
        "gopher://example.com/",
    ],
)
def test_validate_url_blocks(url: str) -> None:
    with pytest.raises(BlockedURL):
        validate_url(url)


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "[::1]", "100.64.1.1", "localhost"]
)
async def test_resolve_blocks_private(host: str) -> None:
    with pytest.raises(BlockedURL):
        await resolve_public(host, 80)


# ------------------------------------------------------------------ chunker / memory filters
def test_chunker_keeps_page_and_header() -> None:
    segs = [Segment("Alpha " * 400, page_number=1), Segment("Beta " * 50, page_number=2)]
    chunks = chunk(segs, "report.pdf")
    assert len(chunks) >= 2
    assert {c.page_number for c in chunks} == {1, 2}
    assert all(c.token_count <= 1000 for c in chunks)


def test_memory_filters() -> None:
    assert memory_service.contains_secret("my key is gsk_abcdefghijklmnopqrstuvwxyz0123456789")
    assert not memory_service.contains_secret("I prefer metric units")
    assert memory_service.should_extract("Please remember that I'm vegetarian")
    assert memory_service.content_hash("Likes  Tea") == memory_service.content_hash("likes tea")


# ------------------------------------------------------------------ memories API
async def test_memory_crud_and_secret_rejection(user_client: Client) -> None:
    c = user_client
    r = await c.post_c("/api/v1/memories", json={"content": "Prefers concise answers"})
    assert r.status_code == 201, r.text
    mid = r.json()["data"]["id"]
    r = await c.post_c("/api/v1/memories", json={"content": "Prefers concise answers"})
    assert r.status_code in (200, 201, 409)
    r = await c.post_c("/api/v1/memories", json={"content": "password is hunter2-secret"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "MEMORY_CONTENT_REJECTED"
    r = await c.get("/api/v1/memories")
    assert [m["id"] for m in r.json()["data"]] == [mid]
    assert (await c.delete_c(f"/api/v1/memories/{mid}")).status_code == 204
    assert (await c.get("/api/v1/memories")).json()["data"] == []


async def test_memories_isolated_between_users(app: Any, user_client: Client) -> None:
    r = await user_client.post_c("/api/v1/memories", json={"content": "Lives in Pune"})
    mid = r.json()["data"]["id"]
    async with make_client(app) as other:
        await signup(other, "rahul@example.com", "Rahul")
        assert (await other.get("/api/v1/memories")).json()["data"] == []
        r = await other.patch_c(f"/api/v1/memories/{mid}", json={"content": "hijacked memory"})
        assert r.status_code == 404


# ------------------------------------------------------------------ files + RAG
async def upload(c: Client, name: str, body: bytes, mime: str) -> dict[str, Any]:
    r = await c.post_c(
        "/api/v1/files", json={"filename": name, "size_bytes": len(body), "mime_type": mime}
    )
    assert r.status_code == 201, r.text
    up = r.json()["data"]["upload"]
    async with httpx.AsyncClient() as s3:
        res = await s3.post(up["url"], data=up["fields"], files={"file": (name, body, mime)})
    assert res.status_code in (200, 204), res.text
    r = await c.post_c(f"/api/v1/files/{r.json()['data']['file']['id']}/complete")
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_upload_needs_no_email_verification(user_client: Client) -> None:
    r = await user_client.post_c(
        "/api/v1/files", json={"filename": "a.txt", "size_bytes": 10, "mime_type": "text/plain"}
    )
    assert r.status_code == 201, r.text


async def test_file_type_rules(user_client: Client) -> None:
    r = await user_client.post_c(
        "/api/v1/files", json={"filename": "x.exe", "size_bytes": 10, "mime_type": "text/plain"}
    )
    assert r.status_code == 415
    r = await user_client.post_c(
        "/api/v1/files", json={"filename": "x.pdf", "size_bytes": 10, "mime_type": "image/png"}
    )
    assert r.json()["error"]["code"] == "FILE_TYPE_MISMATCH"


async def test_upload_process_and_retrieve(app: Any, user_client: Client) -> None:
    from app.documents.pipeline import process_file

    text = b"# Quarterly report\n\nRevenue grew by 42 percent thanks to the monsoon launch.\n"
    f = await upload(user_client, "report.md", text, "text/markdown")
    await process_file(uuid.UUID(f["id"]))
    r = await user_client.get(f"/api/v1/files/{f['id']}")
    assert r.json()["data"]["status"] == "ready", r.text
    async with get_sessionmaker()() as s:
        n = len((await s.execute(select(DocumentChunk))).scalars().all())
    assert n >= 1
    r = await user_client.post_c("/api/v1/rag/search", json={"query": "revenue monsoon"})
    hits = r.json()["data"]
    assert hits and hits[0]["filename"] == "report.md" and "42 percent" in hits[0]["content"]

    # Another user can neither see the file nor retrieve its chunks.
    async with make_client(app) as other:
        await signup(other, "rahul@example.com", "Rahul")
        assert (await other.get(f"/api/v1/files/{f['id']}")).status_code == 404
        r = await other.post_c("/api/v1/rag/search", json={"query": "revenue monsoon"})
        assert r.json()["data"] == []

    assert (await user_client.delete_c(f"/api/v1/files/{f['id']}")).status_code == 204
    r = await user_client.post_c("/api/v1/rag/search", json={"query": "revenue monsoon"})
    assert r.json()["data"] == []


async def test_upload_content_mismatch_rejected(user_client: Client) -> None:
    from app.documents.pipeline import process_file

    f = await upload(user_client, "fake.pdf", b"just text, not a pdf" * 10, "application/pdf")
    await process_file(uuid.UUID(f["id"]))
    async with get_sessionmaker()() as s:
        row = await s.get(File, uuid.UUID(f["id"]))
        assert row is not None and row.status == "rejected"
        assert row.error_code == "FILE_TYPE_MISMATCH"


# ------------------------------------------------------------------ API keys
async def test_api_keys_and_bearer_auth(app: Any, user_client: Client) -> None:
    r = await user_client.post_c("/api/v1/api-keys", json={"name": "ci"})  # any plan (ADR 0004)
    assert r.status_code == 201, r.text
    secret, kid = r.json()["data"]["secret"], r.json()["data"]["id"]
    assert secret.startswith("nova_sk_")
    listed = (await user_client.get("/api/v1/api-keys")).json()["data"]
    assert "secret" not in listed[0]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"x-nova-proxy-secret": "test-proxy-secret-" + "x" * 32},
    ) as api:
        auth = {"authorization": f"Bearer {secret}"}
        assert (await api.get("/api/v1/conversations", headers=auth)).status_code == 200
        # Session-only surfaces refuse API keys.
        assert (await api.get("/api/v1/api-keys", headers=auth)).status_code in (401, 403)
        bad = {"authorization": "Bearer nova_sk_" + "0" * 40}
        assert (await api.get("/api/v1/conversations", headers=bad)).status_code == 401
        assert (await user_client.delete_c(f"/api/v1/api-keys/{kid}")).status_code == 204
        assert (await api.get("/api/v1/conversations", headers=auth)).status_code == 401


# ------------------------------------------------------------------ capabilities / admin
async def test_capabilities_reflect_config(user_client: Client) -> None:
    d = (await user_client.get("/api/v1/capabilities")).json()["data"]
    assert d["documents"]["enabled"] is True
    assert d["web_search"]["enabled"] is False
    assert d["code_execution"]["enabled"] is False
    assert d["video"]["enabled"] is False


async def test_admin_ops_require_admin(user_client: Client) -> None:
    assert (await user_client.get("/api/v1/admin/dashboard")).status_code in (403, 404)
    await set_user(role="admin")
    await relogin(user_client)
    r = await user_client.get("/api/v1/admin/dashboard")
    assert r.status_code == 200, r.text
    r = await user_client.get("/api/v1/admin/health")
    assert r.status_code == 200 and r.json()["data"]["database"]["status"] == "ok"


# ------------------------------------------------------------------ screenshots → vision model
async def test_image_turn_routes_to_vision_model(user_client: Client) -> None:
    import io

    from PIL import Image

    from app.ai.groq import provider as groq_provider
    from app.ai.groq.service import reset_groq_service
    from app.documents.pipeline import process_file
    from tests.fakes import groq_stub

    sc = groq_stub.reset()
    groq_provider.set_http_client_override(groq_stub.client())
    reset_groq_service()
    try:
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), "white").save(buf, "PNG")
        f = await upload(user_client, "screenshot.png", buf.getvalue(), "image/png")
        await process_file(uuid.UUID(f["id"]))
        cid = (await user_client.post_c("/api/v1/conversations", json={})).json()["data"]["id"]
        r = await user_client.post_c(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "What does this show?", "file_ids": [f["id"]]},
            headers={"accept": "application/json"},
        )
        assert r.status_code == 200, r.text
        msg = r.json()["data"]["assistant_message"]
        assert msg["model_key"] == "vision"
        assert msg["status"] == "completed", msg["error"]
        body = sc.requests[-1]
        assert body["model"] == "test-model-vision"
        content = body["messages"][-1]["content"]
        assert any(p.get("type") == "image_url" for p in content)

        # A screenshot alone (no text) can be sent; the model gets an instruction instead of
        # blank text, and the stored message stays empty.
        from app.ai.groq.converters import ATTACHMENTS_ONLY_PROMPT

        f2 = await upload(user_client, "only.png", buf.getvalue(), "image/png")
        await process_file(uuid.UUID(f2["id"]))
        r = await user_client.post_c(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": "", "file_ids": [f2["id"]], "parent_message_id": msg["id"]},
            headers={"accept": "application/json"},
        )
        assert r.status_code == 200, r.text
        user_parts = r.json()["data"]["user_message"]["parts"]
        assert not any((p.get("text") or "").strip() for p in user_parts)
        assert r.json()["data"]["assistant_message"]["status"] == "completed"
        parts = sc.requests[-1]["messages"][-1]["content"]
        assert parts[0] == {"type": "text", "text": ATTACHMENTS_ONLY_PROMPT}
        assert any(p.get("type") == "image_url" for p in parts)
        # Still refused with neither text nor files.
        r = await user_client.post_c(
            f"/api/v1/conversations/{cid}/messages", json={"content": "  "}
        )
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        groq_provider.set_http_client_override(None)
