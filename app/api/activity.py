"""Live activity feed for running executions and in-flight chats."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import get_agent_repo, get_execution_repo
from app.services.repos import AgentRepository, ExecutionRepository
from app.services.stuck_runs import is_stuck

router = APIRouter(tags=["activity"])


def _agent_display_name(agent: Any) -> Optional[str]:
    """UI label: `{name} - {role}` when both are present."""
    if agent is None:
        return None
    name = getattr(agent, "name", None) or None
    if not name:
        return None
    role = (getattr(agent, "role", None) or "").strip()
    return f"{name} - {role}" if role else name


def _duration_seconds(*, start_time: datetime, now: datetime) -> int:
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    else:
        start_time = start_time.astimezone(timezone.utc)
    return max(0, int((now - start_time).total_seconds()))


class ActivityItem(BaseModel):
    id: str
    kind: Literal["run", "chat"]
    agent_id: str
    agent_name: Optional[str] = None
    status: str = "running"
    started_at: datetime
    title: Optional[str] = None
    execution_id: Optional[str] = None
    chat_id: Optional[str] = None
    duration_seconds: int = 0
    is_stuck: bool = False


class ActivityResponse(BaseModel):
    items: list[ActivityItem] = Field(default_factory=list)
    count: int = 0


@router.get("/activity", response_model=ActivityResponse)
async def list_activity(
    request: Request,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    execution_repo: ExecutionRepository = Depends(get_execution_repo),
) -> ActivityResponse:
    agents = {a.id: a for a in await agent_repo.list_all()}
    items: list[ActivityItem] = []
    now = datetime.now(timezone.utc)
    threshold_seconds = request.app.state.settings.run_stuck_seconds

    for log in await execution_repo.list_running(limit=100):
        agent = agents.get(log.agent_id)
        prompt = (log.prompt or "").strip()
        title = prompt[:80] + ("…" if len(prompt) > 80 else "") if prompt else "Agent run"
        run_is_stuck = is_stuck(
            start_time=log.start_time,
            now=now,
            threshold_seconds=threshold_seconds,
        )
        items.append(
            ActivityItem(
                id=f"run:{log.id}",
                kind="run",
                agent_id=log.agent_id,
                agent_name=_agent_display_name(agent),
                status="stuck" if run_is_stuck else log.status.value,
                started_at=log.start_time,
                title=title,
                execution_id=log.id,
                duration_seconds=_duration_seconds(start_time=log.start_time, now=now),
                is_stuck=run_is_stuck,
            )
        )

    activity = getattr(request.app.state, "activity", None)
    chat_rows: list[dict[str, Any]] = activity.chat_items() if activity else []
    for row in chat_rows:
        agent = agents.get(row["agent_id"])
        items.append(
            ActivityItem(
                id=row["id"],
                kind="chat",
                agent_id=row["agent_id"],
                agent_name=_agent_display_name(agent),
                status=row.get("status") or "running",
                started_at=row["started_at"],
                title=row.get("title") or "Chat",
                chat_id=row.get("chat_id"),
            )
        )

    items.sort(key=lambda i: i.started_at, reverse=True)
    return ActivityResponse(items=items, count=len(items))
