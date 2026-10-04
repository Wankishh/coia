"""Stuck-run detection helpers (wall-clock age vs threshold)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.repos import ExecutionRepository


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_stuck(
    *,
    start_time: datetime,
    now: datetime,
    threshold_seconds: int,
) -> bool:
    if threshold_seconds <= 0:
        return False
    age = (_as_utc(now) - _as_utc(start_time)).total_seconds()
    return age >= threshold_seconds


def stuck_error_message(threshold_seconds: int) -> str:
    return f"Stuck: exceeded {threshold_seconds} seconds without completing"


async def sweep_stuck_runs(
    *,
    executions: ExecutionRepository,
    threshold_seconds: int,
    activity: Any = None,
    task_registry: Any = None,
    on_failed: Callable[[str], Awaitable[Any]] | None = None,
) -> int:
    """Fail old running executions and best-effort cancel their local work."""
    if threshold_seconds <= 0:
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=threshold_seconds)
    stuck = await executions.list_running_older_than(cutoff)
    failed = 0
    message = stuck_error_message(threshold_seconds)

    for log in stuck:
        if await executions.fail_if_running(log.id, message):
            failed += 1
            if activity is not None:
                activity.request_execution_cancel(log.id)
            if task_registry is not None:
                task_registry.cancel_for_execution(log.id)
            if on_failed is not None:
                await on_failed(log.id)

    return failed
