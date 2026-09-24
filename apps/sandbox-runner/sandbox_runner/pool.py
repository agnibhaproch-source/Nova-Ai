"""Concurrency slots and the orphan reaper (docs/24 §6)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from sandbox_runner import limits
from sandbox_runner.executor import Executor

log = logging.getLogger("sandbox_runner")


class Busy(Exception):
    pass


class Pool:
    def __init__(self, size: int) -> None:
        self._sem = asyncio.Semaphore(size)

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        try:
            await asyncio.wait_for(self._sem.acquire(), limits.SLOT_WAIT_SECONDS)
        except TimeoutError as e:
            raise Busy from e
        try:
            yield
        finally:
            self._sem.release()


async def reaper(executor: Executor, interval: float = 30) -> None:
    while True:
        try:
            n = await asyncio.to_thread(executor.reap_orphans)
            if n:
                log.warning("sandbox.orphans_removed count=%d", n)
        except Exception:
            log.exception("sandbox.reaper_failed")
        await asyncio.sleep(interval)
