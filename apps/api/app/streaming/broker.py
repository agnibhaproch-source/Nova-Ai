"""GenerationBroker: per-message event streams (docs/13 §4).

Events go to in-process subscribers directly (lowest latency) and are mirrored to a Redis Stream
so any instance can resume/replay. If Redis is unavailable, streaming continues in degraded
mode (no cross-instance resume) — docs/13 §12.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import structlog
from redis.exceptions import RedisError

from app.core.redis import get_redis, rkey

log = structlog.get_logger()
TERMINAL = {"message_complete", "error"}
STREAM_TTL_S = 900
BLOCK_MS = 15000


@dataclass(frozen=True)
class Event:
    seq: int
    event: str
    data: dict[str, Any]


def stream_key(message_id: str) -> str:
    return rkey("gen", message_id)


def state_key(message_id: str) -> str:
    return rkey("gen", message_id, "state")


def cancel_key(message_id: str) -> str:
    return rkey("gen", message_id, "cancel")


class GenerationBroker:
    def __init__(self) -> None:
        self._local: dict[str, list[asyncio.Queue[Event | None]]] = defaultdict(list)
        self._seq: dict[str, int] = {}
        self.degraded = False

    # ---- producer side
    async def open(self, message_id: str) -> None:
        self._seq[message_id] = 0
        try:
            await get_redis().set(state_key(message_id), "running", ex=STREAM_TTL_S * 4)
            self.degraded = False
        except RedisError:
            self.degraded = True
            log.warning("stream.degraded", message_id=message_id)

    async def publish(self, message_id: str, event: str, data: dict[str, Any]) -> Event:
        seq = self._seq.get(message_id, 0) + 1
        self._seq[message_id] = seq
        ev = Event(seq, event, data)
        for q in list(self._local.get(message_id, [])):
            q.put_nowait(ev)
        try:
            redis = get_redis()
            await redis.xadd(
                stream_key(message_id),
                {"seq": seq, "event": event, "data": json.dumps(data, default=str)},
                maxlen=10000,
                approximate=True,
            )
            if event in TERMINAL:
                await redis.expire(stream_key(message_id), STREAM_TTL_S)
                await redis.set(state_key(message_id), "done", ex=STREAM_TTL_S)
        except RedisError:
            self.degraded = True
        if event in TERMINAL:
            for q in self._local.pop(message_id, []):
                q.put_nowait(None)
            self._seq.pop(message_id, None)
        return ev

    # ---- consumer side
    def subscribe_local(self, message_id: str) -> asyncio.Queue[Event | None]:
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        self._local[message_id].append(q)
        return q

    def unsubscribe_local(self, message_id: str, q: asyncio.Queue[Event | None]) -> None:
        qs = self._local.get(message_id)
        if qs and q in qs:
            qs.remove(q)

    def is_local(self, message_id: str) -> bool:
        return message_id in self._seq

    async def replay(self, message_id: str, after_seq: int) -> tuple[list[Event], str, bool]:
        """Returns (events with seq > after_seq, last redis id, complete_history_available)."""
        redis = get_redis()
        entries = await redis.xrange(stream_key(message_id))
        events: list[Event] = []
        first_seq: int | None = None
        last_id = "0-0"
        for entry_id, fields in entries:
            seq = int(fields["seq"])
            first_seq = seq if first_seq is None else first_seq
            last_id = entry_id
            if seq > after_seq:
                events.append(Event(seq, fields["event"], json.loads(fields["data"])))
        complete = bool(entries) and first_seq is not None and first_seq <= after_seq + 1
        return events, last_id, complete

    async def tail(self, message_id: str, last_id: str) -> AsyncIterator[Event | None]:
        """Yields new events from Redis; yields None on each keep-alive timeout."""
        redis = get_redis()
        while True:
            res = await redis.xread({stream_key(message_id): last_id}, block=BLOCK_MS, count=100)
            if not res:
                yield None
                continue
            for _key, entries in res:
                for entry_id, fields in entries:
                    last_id = entry_id
                    yield Event(int(fields["seq"]), fields["event"], json.loads(fields["data"]))

    async def state(self, message_id: str) -> str | None:
        try:
            value = await get_redis().get(state_key(message_id))
            return str(value) if value is not None else None
        except RedisError:
            return None

    async def request_cancel(self, message_id: str) -> None:
        await get_redis().set(cancel_key(message_id), "1", ex=600)

    async def is_cancel_requested(self, message_id: str) -> bool:
        try:
            return bool(await get_redis().exists(cancel_key(message_id)))
        except RedisError:
            return False


broker = GenerationBroker()


def sse_format(ev: Event) -> bytes:
    return f"id: {ev.seq}\nevent: {ev.event}\ndata: {json.dumps(ev.data, default=str)}\n\n".encode()


SSE_PING = b": ping\n\n"
SSE_RETRY = b"retry: 2000\n\n"
