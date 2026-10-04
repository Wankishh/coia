"""Health check endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request

from app.services.stuck_runs import is_stuck

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    mongo_ok = False
    try:
        await request.app.state.mongo.admin.command("ping")
        mongo_ok = True
    except Exception:  # noqa: BLE001
        mongo_ok = False

    running = 0
    stuck = 0
    try:
        logs = await request.app.state.execution_repo.list_running(limit=100)
        running = len(logs)
        now = datetime.now(timezone.utc)
        stuck = sum(
            is_stuck(
                start_time=log.start_time,
                now=now,
                threshold_seconds=settings.run_stuck_seconds,
            )
            for log in logs
        )
    except Exception:  # noqa: BLE001
        pass

    status = "ok" if mongo_ok else "degraded"
    if stuck:
        status = "degraded"

    return {
        "status": status,
        "service": "coia-agent-harness",
        "mongo": "up" if mongo_ok else "down",
        "scheduler": (
            "running" if request.app.state.scheduler.scheduler.running else "stopped"
        ),
        "running_executions": running,
        "stuck_executions": stuck,
        "run_stuck_seconds": settings.run_stuck_seconds,
    }
