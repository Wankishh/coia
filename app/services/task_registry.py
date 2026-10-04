"""Process-level registry for background agent run tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, Optional, Set

logger = logging.getLogger(__name__)


class TaskRegistry:
    """Track asyncio tasks created for agent runs; support graceful drain on shutdown."""

    def __init__(self) -> None:
        self._tasks: Set[asyncio.Task[Any]] = set()

    @property
    def tasks(self) -> Set[asyncio.Task[Any]]:
        return self._tasks

    def create_task(
        self,
        coro: Coroutine[Any, Any, Any],
        *,
        name: Optional[str] = None,
    ) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_done)
        return task

    def cancel_for_execution(self, execution_id: str) -> bool:
        """Best-effort cancel of a background run task named *-{execution_id}."""
        cancelled = False
        for task in list(self._tasks):
            name = task.get_name() or ""
            if execution_id in name and not task.done():
                task.cancel()
                cancelled = True
        return cancelled

    def _on_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Background task %s failed: %s", task.get_name(), exc)

    async def wait_shutdown(self, timeout: float = 30.0) -> None:
        """Await in-flight tasks up to timeout, then cancel leftovers."""
        pending = {t for t in self._tasks if not t.done()}
        if not pending:
            return

        logger.info("Waiting for %d background task(s) (timeout=%.1fs)", len(pending), timeout)
        done, still_pending = await asyncio.wait(pending, timeout=timeout)
        logger.info(
            "Shutdown wait finished: %d done, %d still pending",
            len(done),
            len(still_pending),
        )
        for task in still_pending:
            task.cancel()
        if still_pending:
            await asyncio.wait(still_pending, timeout=5.0)
