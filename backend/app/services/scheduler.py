"""Background loop that ticks the follow engine on an interval.

Started/stopped from the FastAPI lifespan. Errors in a tick are logged and
swallowed so a transient API hiccup never kills the loop.
"""
from __future__ import annotations

import asyncio
import logging

from app.services.engine import FollowEngine

log = logging.getLogger("copybot.scheduler")


class EngineScheduler:
    def __init__(self, engine: FollowEngine, interval_seconds: int = 30):
        self.engine = engine
        self.interval = interval_seconds
        self._task: asyncio.Task | None = None
        self.last_summary: dict | None = None

    async def _run(self) -> None:
        log.info("engine scheduler started (every %ds)", self.interval)
        while True:
            try:
                self.last_summary = await self.engine.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("engine tick failed: %s", exc)
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def tick_now(self) -> dict:
        """Run one tick immediately (used by the manual trigger endpoint)."""
        self.last_summary = await self.engine.tick()
        return self.last_summary
