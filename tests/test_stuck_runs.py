"""Unit tests for stuck-run age detection."""

from datetime import datetime, timedelta, timezone

from app.services.stuck_runs import is_stuck


def test_is_stuck_when_older_than_threshold() -> None:
    start = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    now = start + timedelta(seconds=1801)

    assert is_stuck(start_time=start, now=now, threshold_seconds=1800) is True


def test_is_stuck_false_when_within_threshold() -> None:
    start = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    now = start + timedelta(seconds=100)

    assert is_stuck(start_time=start, now=now, threshold_seconds=1800) is False
