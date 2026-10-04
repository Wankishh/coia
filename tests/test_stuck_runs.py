"""Unit tests for stuck-run age detection."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.stuck_runs import is_stuck, sweep_stuck_runs


def test_is_stuck_when_older_than_threshold() -> None:
    start = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    now = start + timedelta(seconds=1801)

    assert is_stuck(start_time=start, now=now, threshold_seconds=1800) is True


def test_is_stuck_false_when_within_threshold() -> None:
    start = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    now = start + timedelta(seconds=100)

    assert is_stuck(start_time=start, now=now, threshold_seconds=1800) is False


def test_sweep_stuck_runs_fails_with_stuck_message() -> None:
    class FakeExecutionRepository:
        def __init__(self) -> None:
            self.fail_calls: list[tuple[str, str]] = []

        async def list_running_older_than(self, cutoff: datetime) -> list[object]:
            return [SimpleNamespace(id="execution-1")]

        async def fail_if_running(
            self,
            execution_id: str,
            error_message: str,
        ) -> bool:
            self.fail_calls.append((execution_id, error_message))
            return True

    repo = FakeExecutionRepository()
    failed = asyncio.run(
        sweep_stuck_runs(
            executions=repo,  # type: ignore[arg-type]
            threshold_seconds=1800,
        )
    )

    assert failed == 1
    assert repo.fail_calls[0][0] == "execution-1"
    assert repo.fail_calls[0][1].startswith("Stuck:")


def test_sweep_cancels_only_executions_it_transitions_to_failed() -> None:
    events: list[tuple[str, str]] = []

    class FakeExecutionRepository:
        async def list_running_older_than(self, cutoff: datetime) -> list[object]:
            return [
                SimpleNamespace(id="already-terminal"),
                SimpleNamespace(id="still-running"),
            ]

        async def fail_if_running(
            self,
            execution_id: str,
            error_message: str,
        ) -> bool:
            events.append(("fail", execution_id))
            return execution_id == "still-running"

    class FakeActivity:
        def request_execution_cancel(self, execution_id: str) -> None:
            events.append(("activity-cancel", execution_id))

    class FakeTaskRegistry:
        def cancel_for_execution(self, execution_id: str) -> None:
            events.append(("task-cancel", execution_id))

    async def on_failed(execution_id: str) -> None:
        events.append(("on-failed", execution_id))

    failed = asyncio.run(
        sweep_stuck_runs(
            executions=FakeExecutionRepository(),  # type: ignore[arg-type]
            threshold_seconds=1800,
            activity=FakeActivity(),
            task_registry=FakeTaskRegistry(),
            on_failed=on_failed,
        )
    )

    assert failed == 1
    assert events == [
        ("fail", "already-terminal"),
        ("fail", "still-running"),
        ("activity-cancel", "still-running"),
        ("task-cancel", "still-running"),
        ("on-failed", "still-running"),
    ]
