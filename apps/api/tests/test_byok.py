"""BYOK: each conversation runs on the Groq key its owner supplied (app/ai/groq/keys.py)."""

from __future__ import annotations

from typing import Any

import pytest

from app.ai.groq import provider as groq_provider
from app.ai.groq.service import reset_groq_service
from app.core.config import get_settings
from app.core.redis import get_redis, rkey
from tests.conftest import Client, make_client, signup
from tests.fakes import groq_stub
from tests.test_chat import SSE, parse_sse

USER_KEY = "gsk_user_supplied_key_1234567890"


@pytest.fixture(autouse=True)
def byok(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(get_settings(), "GROQ_KEY_MODE", "user")
    sc = groq_stub.reset()
    groq_provider.set_http_client_override(groq_stub.client())
    reset_groq_service()
    yield sc
    groq_provider.set_http_client_override(None)


async def create(c: Client, key: str | None) -> Any:
    body = {"groq_api_key": key} if key is not None else {}
    return await c.post_c("/api/v1/conversations", json=body)


async def test_new_chat_requires_a_key(user_client: Client) -> None:
    r = await create(user_client, None)
    assert r.status_code == 428 and r.json()["error"]["code"] == "GROQ_KEY_REQUIRED"


async def test_rejected_key_is_not_stored(user_client: Client) -> None:
    r = await create(user_client, "gsk_revoked_key_000000000000")
    assert r.status_code == 422 and r.json()["error"]["code"] == "GROQ_KEY_INVALID"
    r = await create(user_client, "not-a-groq-key")
    assert r.status_code == 422
    assert (await user_client.get("/api/v1/conversations")).json()["data"] == []


async def test_chat_uses_the_conversation_key(user_client: Client, byok: Any) -> None:
    r = await create(user_client, USER_KEY)
    assert r.status_code == 201, r.text
    cid = r.json()["data"]["id"]
    raw = await get_redis().get(rkey("groqkey", cid))
    assert raw and USER_KEY not in str(raw)  # encrypted at rest in Redis
    status = (await user_client.get(f"/api/v1/conversations/{cid}/groq-key")).json()["data"]
    assert status["configured"] and "api_key" not in status

    r = await user_client.post_c(
        f"/api/v1/conversations/{cid}/messages", json={"content": "hi"}, headers=SSE
    )
    events = [e[1] for e in parse_sse(r.text)]
    assert events[-1] == "message_complete", r.text
    chat_keys = byok.keys_seen[1:]  # [0] is the validation call
    assert chat_keys and set(chat_keys) == {USER_KEY}


async def test_expired_key_blocks_until_reentered(user_client: Client) -> None:
    cid = (await create(user_client, USER_KEY)).json()["data"]["id"]
    assert (await user_client.delete_c(f"/api/v1/conversations/{cid}/groq-key")).status_code == 204
    r = await user_client.post_c(
        f"/api/v1/conversations/{cid}/messages", json={"content": "hi"}, headers=SSE
    )
    assert r.status_code == 428
    msgs = (await user_client.get(f"/api/v1/conversations/{cid}/messages")).json()["data"]
    assert msgs == []  # nothing persisted for the refused turn
    r = await user_client.put_c(f"/api/v1/conversations/{cid}/groq-key", json={"api_key": USER_KEY})
    assert r.status_code == 200 and r.json()["data"]["configured"]


async def test_keys_are_per_conversation_and_owner(app: Any, user_client: Client) -> None:
    cid = (await create(user_client, USER_KEY)).json()["data"]["id"]
    async with make_client(app) as other:
        await signup(other, "rahul@example.com", "Rahul")
        assert (await other.get(f"/api/v1/conversations/{cid}/groq-key")).status_code == 404
        r = await other.put_c(f"/api/v1/conversations/{cid}/groq-key", json={"api_key": USER_KEY})
        assert r.status_code == 404, r.text
