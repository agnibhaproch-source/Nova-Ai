"""SSE response helpers: live stream, resume/replay, snapshot (docs/13 §2, §7)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import structlog
from fastapi import Request
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError

from app.db.session import get_sessionmaker
from app.models import Message
from app.services import message_service
from app.streaming.broker import SSE_PING, SSE_RETRY, TERMINAL, Event, broker, sse_format

log = structlog.get_logger("app.sse")
PING_S = 15.0
HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_response(gen: AsyncIterator[bytes]) -> StreamingResponse:
    return StreamingResponse(gen, media_type="text/event-stream; charset=utf-8", headers=HEADERS)


async def _from_queue(
    request: Request, q: asyncio.Queue[Event | None], message_id: str, after_seq: int = 0
) -> AsyncIterator[bytes]:
    last = after_seq
    try:
        while True:
            if await request.is_disconnected():
                log.info("sse.stream.closed", message_id=message_id, reason="client_disconnect")
                return
            try:
                ev = await asyncio.wait_for(q.get(), PING_S)
            except TimeoutError:
                yield SSE_PING
                continue
            if ev is None:
                return
            if ev.seq <= last:
                continue
            last = ev.seq
            yield sse_format(ev)
            if ev.event in TERMINAL:
                return
    finally:
        broker.unsubscribe_local(message_id, q)


def live_stream(
    request: Request, q: asyncio.Queue[Event | None], message_id: str
) -> StreamingResponse:
    async def gen() -> AsyncIterator[bytes]:
        yield SSE_RETRY
        async for chunk in _from_queue(request, q, message_id):
            yield chunk

    return sse_response(gen())


async def _snapshot_events(message_id: uuid.UUID) -> tuple[list[Event], str]:
    async with get_sessionmaker()() as db:
        msg = await db.get(Message, message_id)
        assert msg is not None
        data = (await message_service.serialize(db, [msg]))[0]
    events = [Event(0, "message_snapshot", {"message": data})]
    if msg.status in ("completed", "cancelled"):
        events.append(
            Event(
                0,
                "message_complete",
                {
                    "message_id": str(msg.id),
                    "status": msg.status,
                    "finish_reason": msg.finish_reason,
                    "message": data,
                },
            )
        )
    elif msg.status == "failed":
        events.append(
            Event(
                0,
                "error",
                {
                    "message_id": str(msg.id),
                    "code": msg.error_code or "INTERNAL_ERROR",
                    "message": (data.get("error") or {}).get("message", "The response failed."),
                    "retryable": True,
                    "retry_after_seconds": None,
                },
            )
        )
    return events, msg.status


def resume_stream(request: Request, message_id: uuid.UUID, last_event_id: int) -> StreamingResponse:
    mid = str(message_id)

    async def gen() -> AsyncIterator[bytes]:
        yield SSE_RETRY
        local_q = broker.subscribe_local(mid) if broker.is_local(mid) else None
        try:
            events, last_redis_id, complete = await broker.replay(mid, last_event_id)
        except RedisError:
            events, last_redis_id, complete = [], "0-0", False
        last_seq = last_event_id
        if complete or (last_event_id == 0 and events and events[0].seq == 1):
            for ev in events:
                last_seq = ev.seq
                yield sse_format(ev)
                if ev.event in TERMINAL:
                    if local_q:
                        broker.unsubscribe_local(mid, local_q)
                    return
        else:
            snapshot, status = await _snapshot_events(message_id)
            for ev in snapshot:
                yield sse_format(ev)
            if status in message_service.TERMINAL:
                if local_q:
                    broker.unsubscribe_local(mid, local_q)
                return
            last_seq = events[-1].seq if events else last_event_id
        if local_q is not None:
            async for chunk in _from_queue(request, local_q, mid, after_seq=last_seq):
                yield chunk
            return
        state = await broker.state(mid)
        if state is None:
            await asyncio.sleep(5)
            snapshot, status = await _snapshot_events(message_id)
            if status in message_service.TERMINAL:
                for ev in snapshot[1:]:
                    yield sse_format(ev)
                return
            yield sse_format(
                Event(
                    0,
                    "error",
                    {
                        "message_id": mid,
                        "code": "GENERATION_INTERRUPTED",
                        "message": "The response was interrupted. Retry to generate it again.",
                        "retryable": True,
                        "retry_after_seconds": None,
                    },
                )
            )
            return
        async for tev in broker.tail(mid, last_redis_id):
            if await request.is_disconnected():
                return
            if tev is None:
                yield SSE_PING
                continue
            if tev.seq <= last_seq:
                continue
            last_seq = tev.seq
            yield sse_format(tev)
            if tev.event in TERMINAL:
                return

    return sse_response(gen())
