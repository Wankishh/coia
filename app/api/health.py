"""Health check endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    mongo_ok = False
    try:
        await request.app.state.mongo.admin.command("ping")
        mongo_ok = True
    except Exception:  # noqa: BLE001
        mongo_ok = False

    status = "ok" if mongo_ok else "degraded"
    return {
        "status": status,
        "service": "coia-agent-harness",
        "mongo": "up" if mongo_ok else "down",
        "scheduler": (
            "running" if request.app.state.scheduler.scheduler.running else "stopped"
        ),
    }
