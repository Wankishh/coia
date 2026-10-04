"""Stuck-run detection helpers (wall-clock age vs threshold)."""

from __future__ import annotations

from datetime import datetime, timezone


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
