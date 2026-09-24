"""Phase 2: conversations, streaming chat, branches, cancel, resume, quotas (docs/11–16)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from sqlalchemy import select

from app.ai.groq import provider as groq_provider
from app.ai.groq.service import reset_groq_service
from app.core.redis import get_redis, rkey
from app.db.session import get_sessionmaker
from app.models import Conversation, Message, UsageRecord
from app.services import title_service
from tests.conftest import Client, make_client, signup
from tests.fakes import groq_stub

SSE = {"accept": "text/event-stream"}


@pytest.fixture(autouse=True)
def stub() -> Any:
    sc = groq_stub.reset()
    groq_provider.set_http_client_override(groq_stub.client())
    reset_groq_service()
    yield sc
    groq_provider.set_http_client_override(None)


def parse_sse(raw: str) -> list[tuple[int | None, str, dict[str, Any]]]:
    events = []
    for block in raw.split("\n\n"):
        eid, name, data = None, None, None
        for line in block.split("\n"):
            if line.startswith("id: "):
                eid = int(line[4:])
            elif line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((eid, name, data or {}))
    return events


async def new_conversation(c: Client) -> str:
    r = await c.post_c("/api/v1/conversations", json={})
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def send(c: Client, cid: str, content: str, **headers: str) -> list[Any]:
    r = await c.post_c(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": content},
        headers={**SSE, **headers},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return parse_sse(r.text)


async def test_streamed_turn_end_to_end(user_client: Client, stub: Any) -> None:
    stub.reply = "Paris is the capital of France."
    cid = await new_conversation(user_client)
    events = await send(user_client, cid, "What is the capital of France?")
    names = [e[1] for e in events]
    assert names[0] == "message_start" and names[-1] == "message_complete"
    assert "content_delta" in names and "usage" in names
    ids = [e[0] for e in events]
    assert ids == sorted(ids) and ids[0] == 1
    text = "".join(e[2]["delta"] for e in events if e[1] == "content_delta")
    assert text == stub.reply
    final = events[-1][2]["message"]
    assert final["status"] == "completed" and final["parts"][0]["text"] == stub.reply
    # Groq request: system prompt first, user message last, opaque user hash, no PII
    req = stub.requests[-1]
    assert req["messages"][0]["role"] == "system" and req["messages"][-1]["content"] == (
        "What is the capital of France?"
    )
    assert req["model"] == "test-model-primary" and "@" not in req.get("user", "")
    r = await user_client.get(f"/api/v1/conversations/{cid}/messages")
    msgs = r.json()["data"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    async with get_sessionmaker()() as s:
        rec = await s.scalar(select(UsageRecord).where(UsageRecord.kind == "chat"))
        assert rec is not None and rec.total_tokens > 0 and rec.estimated_cost_usd_micros


async def test_json_mode_and_second_turn_includes_history(user_client: Client, stub: Any) -> None:
    cid = await new_conversation(user_client)
    r = await user_client.post_c(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "hi"},
        headers={"accept": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["assistant_message"]["status"] == "completed"
    await send(user_client, cid, "and again")
    roles = [m["role"] for m in stub.requests[-1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


async def test_regenerate_and_branch_navigation(user_client: Client, stub: Any) -> None:
    cid = await new_conversation(user_client)
    first = (await send(user_client, cid, "Tell me a joke"))[-1][2]["message"]
    stub.reply = "A different joke."
    r = await user_client.post_c(f"/api/v1/messages/{first['id']}/regenerate", json={}, headers=SSE)
    second = parse_sse(r.text)[-1][2]["message"]
    assert second["siblings"]["count"] == 2 and second["siblings"]["index"] == 1
    r = await user_client.post_c(
        f"/api/v1/conversations/{cid}/branch", json={"message_id": first["id"]}
    )
    assert r.json()["data"][-1]["id"] == first["id"]
    assert r.json()["data"][-1]["siblings"]["next_id"] == second["id"]


async def test_edit_creates_new_branch(user_client: Client, stub: Any) -> None:
    cid = await new_conversation(user_client)
    events = await send(user_client, cid, "Original question")
    user_msg = events[0][2]["user_message"]
    r = await user_client.post_c(
        f"/api/v1/messages/{user_msg['id']}/edit", json={"content": "Edited question"}, headers=SSE
    )
    ev = parse_sse(r.text)
    assert ev[0][2]["user_message"]["siblings"]["count"] == 2
    msgs = (await user_client.get(f"/api/v1/conversations/{cid}/messages")).json()["data"]
    assert msgs[0]["parts"][0]["text"] == "Edited question"


async def test_cancel_mid_stream_persists_partial(app: Any, stub: Any) -> None:
    stub.reply = "word " * 200
    stub.chunk_size = 5
    stub.delay_s = 0.02
    async with make_client(app) as c:
        await signup(c)
        cid = await new_conversation(c)
        task = asyncio.create_task(
            c.post_c(
                f"/api/v1/conversations/{cid}/messages",
                json={"content": "long please"},
                headers=SSE,
            )
        )
        mid = None
        for _ in range(100):
            await asyncio.sleep(0.05)
            async with get_sessionmaker()() as s:
                m = await s.scalar(
                    select(Message).where(
                        Message.role == "assistant", Message.status == "streaming"
                    )
                )
                if m:
                    mid = m.id
                    break
        assert mid is not None
        r = await c.post_c(f"/api/v1/messages/{mid}/cancel")
        assert r.status_code == 202
        resp = await asyncio.wait_for(task, 10)
        events = parse_sse(resp.text)
        assert events[-1][1] == "message_complete"
        assert events[-1][2]["status"] == "cancelled"
        assert stub.stream_closed
        async with get_sessionmaker()() as s:
            m = await s.get(Message, mid)
            assert m.status == "cancelled" and 0 < len(m.content_text) < len(stub.reply)


async def test_resume_replays_from_last_event_id(user_client: Client, stub: Any) -> None:
    cid = await new_conversation(user_client)
    events = await send(user_client, cid, "hello")
    mid = events[-1][2]["message_id"]
    r = await user_client.get(f"/api/v1/messages/{mid}/stream", headers={"last-event-id": "2"})
    replay = parse_sse(r.text)
    assert replay[0][0] == 3 and replay[-1][1] == "message_complete"
    await get_redis().delete(rkey("gen", mid))  # stream expired → snapshot path
    r = await user_client.get(f"/api/v1/messages/{mid}/stream", headers={"last-event-id": "2"})
    names = [e[1] for e in parse_sse(r.text)]
    assert names == ["message_snapshot", "message_complete"]


async def test_idempotency_key_prevents_duplicates(user_client: Client) -> None:
    cid = await new_conversation(user_client)
    await send(user_client, cid, "same", **{"idempotency-key": "k-123"})
    await send(user_client, cid, "same", **{"idempotency-key": "k-123"})
    async with get_sessionmaker()() as s:
        n = len((await s.execute(select(Message).where(Message.role == "user"))).all())
    assert n == 1
    r = await user_client.post_c(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "different"},
        headers={**SSE, "idempotency-key": "k-123"},
    )
    assert r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_provider_retry_then_failure(user_client: Client, stub: Any) -> None:
    stub.fail_statuses = [500]  # one failure, retried transparently
    cid = await new_conversation(user_client)
    events = await send(user_client, cid, "retry me")
    assert events[-1][1] == "message_complete"
    stub.fail_statuses = [500, 500, 500]
    events = await send(user_client, cid, "fail me")
    assert events[-1][1] == "error" and events[-1][2]["code"] == "PROVIDER_UNAVAILABLE"
    assert events[-1][2]["retryable"] is True
    msgs = (await user_client.get(f"/api/v1/conversations/{cid}/messages")).json()["data"]
    assert msgs[-1]["status"] == "failed"


async def test_cross_user_access_is_404(app: Any) -> None:
    async with make_client(app) as a, make_client(app) as b:
        await signup(a, "a@example.com", "A")
        await signup(b, "b@example.com", "B")
        cid = await new_conversation(a)
        events = await send(a, cid, "private")
        mid = events[-1][2]["message_id"]
        for r in [
            await b.get(f"/api/v1/conversations/{cid}"),
            await b.get(f"/api/v1/conversations/{cid}/messages"),
            await b.get(f"/api/v1/messages/{mid}"),
            await b.post_c(f"/api/v1/messages/{mid}/regenerate", json={}),
            await b.post_c(
                f"/api/v1/conversations/{cid}/messages", json={"content": "x"}, headers=SSE
            ),
            await b.delete_c(f"/api/v1/conversations/{cid}"),
        ]:
            assert r.status_code == 404, r.text


async def test_quota_exceeded(user_client: Client) -> None:
    cid = await new_conversation(user_client)
    async with get_sessionmaker()() as s:
        uid = await s.scalar(select(Conversation.user_id))
    from app.services.quota_service import _day

    await get_redis().set(rkey("q", "msg", uid, _day()), 50)
    r = await user_client.post_c(
        f"/api/v1/conversations/{cid}/messages", json={"content": "one more"}, headers=SSE
    )
    assert r.status_code == 429 and r.json()["error"]["code"] == "QUOTA_EXCEEDED"
    assert "retry-after" in r.headers


async def test_conversation_lifecycle_and_search(user_client: Client, stub: Any) -> None:
    stub.reply = "Photosynthesis converts light into chemical energy."
    cid = await new_conversation(user_client)
    await send(user_client, cid, "explain photosynthesis")
    r = await user_client.get("/api/v1/conversations/search", params={"q": "photosynthesis"})
    hit = r.json()["data"][0]
    assert hit["conversation_id"] == cid and hit["highlights"]
    r = await user_client.patch_c(
        f"/api/v1/conversations/{cid}", json={"title": "Biology", "pinned": True}
    )
    assert r.json()["data"]["title"] == "Biology" and r.json()["data"]["pinned"]
    listed = (await user_client.get("/api/v1/conversations")).json()["data"]
    assert [c["id"] for c in listed] == [cid]
    assert (await user_client.delete_c(f"/api/v1/conversations/{cid}")).status_code == 204
    assert (await user_client.get("/api/v1/conversations")).json()["data"] == []
    trash = (await user_client.get("/api/v1/conversations?deleted=true")).json()["data"]
    assert trash[0]["purge_at"]
    r = await user_client.post_c(f"/api/v1/conversations/{cid}/restore")
    assert r.json()["data"]["deleted_at"] is None
    await user_client.delete_c(f"/api/v1/conversations/{cid}")
    r = await user_client.delete_c(f"/api/v1/conversations/{cid}?permanent=true")
    assert r.status_code == 204


async def test_pagination_is_stable(user_client: Client) -> None:
    from sqlalchemy import update

    from app.models import User

    async with get_sessionmaker()() as s:  # pro plan: higher chat burst (docs/34 §4)
        await s.execute(update(User).values(plan_key="pro"))
        await s.commit()
    await get_redis().flushdb()  # drop the cached session so the new plan is picked up
    await user_client.post(
        "/api/v1/auth/login",
        json={"email": "priya@example.com", "password": "correct-horse-battery-9"},
    )
    ids = []
    for i in range(5):
        cid = await new_conversation(user_client)
        await send(user_client, cid, f"message {i}")
        ids.append(cid)
    seen, cursor = [], None
    while True:
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        body = (await user_client.get("/api/v1/conversations", params=params)).json()
        seen += [c["id"] for c in body["data"]]
        cursor = body["page"]["next_cursor"]
        if not cursor:
            break
    assert seen == list(reversed(ids))
    r = await user_client.get("/api/v1/conversations", params={"cursor": "tampered.x"})
    assert r.json()["error"]["code"] == "INVALID_CURSOR"


async def test_title_generation(user_client: Client, stub: Any) -> None:
    cid = await new_conversation(user_client)
    await send(user_client, cid, "How do vaccines work?")
    stub.reply = '"How Vaccines Work."'
    import uuid

    title = await title_service.generate_title(uuid.UUID(cid))
    assert title == "How Vaccines Work"
    conv = (await user_client.get(f"/api/v1/conversations/{cid}")).json()["data"]
    assert conv["title"] == "How Vaccines Work" and conv["title_source"] == "generated"


async def test_feedback(user_client: Client) -> None:
    cid = await new_conversation(user_client)
    mid = (await send(user_client, cid, "hi"))[-1][2]["message_id"]
    r = await user_client.put_c(
        f"/api/v1/messages/{mid}/feedback", json={"rating": "down", "reasons": ["inaccurate"]}
    )
    assert r.status_code == 200
    msg = (await user_client.get(f"/api/v1/messages/{mid}")).json()["data"]
    assert msg["feedback"]["rating"] == "down"


async def test_models_endpoint_hides_groq_ids(user_client: Client) -> None:
    r = await user_client.get("/api/v1/models")
    models = r.json()["data"]
    assert {m["key"] for m in models} == {"primary", "fast", "vision"}
    assert "test-model" not in r.text
