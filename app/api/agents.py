"""Agent CRUD and run endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent_templates import AgentTemplate, list_agent_templates
from app.api.deps import (
    get_agent_repo,
    get_execution_repo,
    get_runner,
    get_scheduler,
    get_settings,
    get_source_repo,
    get_status_service,
)
from app.config import Settings
from app.models.agent import (
    AgentCreate,
    AgentPublic,
    AgentUpdate,
    to_public,
)
from app.models.execution import ExecutionLog, TriggerType
from app.scheduler import AgentScheduler, validate_cron
from app.services.agent_avatars import (
    AgentAvatarError,
    clear_avatar_files,
    find_avatar_file,
    normalize_preset,
    save_avatar_upload,
)
from app.services.agent_runner import AgentRunner
from app.services.agent_status import (
    AgentStatusInfo,
    AgentStatusService,
    clear_status_cache,
)
from app.services.repos import (
    AgentAlreadyRunningError,
    AgentRepository,
    ExecutionRepository,
    SourceRepository,
)
from app.services.source_resolve import resolve_agent_sources

router = APIRouter(tags=["agents"])


def _normalize_avatar_preset(value: Optional[str]) -> Optional[str]:
    try:
        return normalize_preset(value)
    except AgentAvatarError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agent-templates", response_model=list[AgentTemplate])
async def get_agent_templates() -> list[AgentTemplate]:
    """Built-in role templates for the admin create-agent flow (no secrets)."""
    return list_agent_templates()


class RunRequest(BaseModel):
    prompt: Optional[str] = Field(
        default=None,
        description="Optional prompt override; falls back to agent default_prompt",
    )


class RunAccepted(BaseModel):
    execution_id: str


def _require_valid_cron(cron_schedule: Optional[str]) -> None:
    if not cron_schedule:
        return
    try:
        validate_cron(cron_schedule)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cron_schedule: {exc}",
        ) from exc


def _sync_agent_schedule(scheduler: AgentScheduler, agent) -> None:
    """Schedule cron only when agent has a schedule and is not paused."""
    if agent.paused or not agent.cron_schedule:
        scheduler.unschedule_agent(agent.id)
    else:
        scheduler.schedule_agent(agent.id, agent.cron_schedule)


async def _public_agent(
    agent,
    source_repo: SourceRepository,
    status_service: Optional[AgentStatusService] = None,
    *,
    force_status: bool = False,
) -> AgentPublic:
    resolved = await resolve_agent_sources(agent, source_repo)
    status_info: Optional[AgentStatusInfo] = None
    if status_service is not None:
        status_info = await status_service.get_status(agent, force=force_status)
    if status_info is not None:
        return to_public(
            agent,
            resolved_sources=resolved,
            status=status_info.status,
            status_label=status_info.status_label,
            error_message=status_info.error_message,
            checked_at=status_info.checked_at,
        )
    return to_public(agent, resolved_sources=resolved)


@router.post("/agents", response_model=AgentPublic, status_code=201)
async def create_agent(
    payload: AgentCreate,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    source_repo: SourceRepository = Depends(get_source_repo),
    scheduler: AgentScheduler = Depends(get_scheduler),
    status_service: AgentStatusService = Depends(get_status_service),
) -> AgentPublic:
    _require_valid_cron(payload.cron_schedule)
    payload.avatar_preset = _normalize_avatar_preset(payload.avatar_preset)
    if payload.source_ids:
        found = await source_repo.get_many(payload.source_ids)
        found_ids = {s.id for s in found}
        missing = [sid for sid in payload.source_ids if sid not in found_ids]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown source_ids: {', '.join(missing)}",
            )
    agent = await agent_repo.create(payload)
    _sync_agent_schedule(scheduler, agent)
    return await _public_agent(
        agent, source_repo, status_service, force_status=True
    )


@router.get("/agents", response_model=list[AgentPublic])
async def list_agents(
    agent_repo: AgentRepository = Depends(get_agent_repo),
    source_repo: SourceRepository = Depends(get_source_repo),
    status_service: AgentStatusService = Depends(get_status_service),
) -> list[AgentPublic]:
    agents = await agent_repo.list_all()
    status_map = await status_service.get_status_many(agents)
    result: list[AgentPublic] = []
    for agent in agents:
        resolved = await resolve_agent_sources(agent, source_repo)
        info = status_map.get(agent.id)
        if info is None:
            result.append(to_public(agent, resolved_sources=resolved))
            continue
        result.append(
            to_public(
                agent,
                resolved_sources=resolved,
                status=info.status,
                status_label=info.status_label,
                error_message=info.error_message,
                checked_at=info.checked_at,
            )
        )
    return result


@router.get("/agents/{agent_id}", response_model=AgentPublic)
async def get_agent(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    source_repo: SourceRepository = Depends(get_source_repo),
    status_service: AgentStatusService = Depends(get_status_service),
) -> AgentPublic:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await _public_agent(agent, source_repo, status_service)


@router.patch("/agents/{agent_id}", response_model=AgentPublic)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    source_repo: SourceRepository = Depends(get_source_repo),
    scheduler: AgentScheduler = Depends(get_scheduler),
    status_service: AgentStatusService = Depends(get_status_service),
    settings: Settings = Depends(get_settings),
) -> AgentPublic:
    updates = payload.model_dump(exclude_unset=True)
    if "cron_schedule" in updates:
        _require_valid_cron(payload.cron_schedule)
    clear_uploaded_avatar = False
    if "avatar_preset" in updates:
        normalized = _normalize_avatar_preset(payload.avatar_preset)
        payload = payload.model_copy(update={"avatar_preset": normalized})
        updates["avatar_preset"] = normalized
        # Selecting a preset clears a custom upload.
        if normalized is not None:
            clear_uploaded_avatar = True

    if "source_ids" in updates and payload.source_ids is not None:
        found = await source_repo.get_many(payload.source_ids)
        found_ids = {s.id for s in found}
        missing = [sid for sid in payload.source_ids if sid not in found_ids]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown source_ids: {', '.join(missing)}",
            )

    agent = await agent_repo.update(agent_id, payload)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    if clear_uploaded_avatar:
        clear_avatar_files(settings.workspace_path, agent_id)
        agent = await agent_repo.set_avatar(
            agent_id,
            clear_path=True,
            avatar_preset=updates["avatar_preset"],
        ) or agent

    # Reschedule when cron or paused changed (pause unschedules; resume restores).
    if "cron_schedule" in updates or "paused" in updates:
        _sync_agent_schedule(scheduler, agent)
    # API key / provider changes should invalidate cached readiness.
    return await _public_agent(
        agent, source_repo, status_service, force_status=True
    )


@router.post("/agents/{agent_id}/pause", response_model=AgentPublic)
async def pause_agent(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    source_repo: SourceRepository = Depends(get_source_repo),
    scheduler: AgentScheduler = Depends(get_scheduler),
    status_service: AgentStatusService = Depends(get_status_service),
) -> AgentPublic:
    agent = await agent_repo.update(agent_id, AgentUpdate(paused=True))
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    scheduler.unschedule_agent(agent.id)
    return await _public_agent(agent, source_repo, status_service)


@router.post("/agents/{agent_id}/resume", response_model=AgentPublic)
async def resume_agent(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    source_repo: SourceRepository = Depends(get_source_repo),
    scheduler: AgentScheduler = Depends(get_scheduler),
    status_service: AgentStatusService = Depends(get_status_service),
) -> AgentPublic:
    agent = await agent_repo.update(agent_id, AgentUpdate(paused=False))
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    _sync_agent_schedule(scheduler, agent)
    return await _public_agent(agent, source_repo, status_service)


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    scheduler: AgentScheduler = Depends(get_scheduler),
    settings: Settings = Depends(get_settings),
) -> None:
    deleted = await agent_repo.delete(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    scheduler.unschedule_agent(agent_id)
    clear_status_cache(agent_id)
    clear_avatar_files(settings.workspace_path, agent_id)


@router.post("/agents/{agent_id}/avatar", response_model=AgentPublic)
async def upload_agent_avatar(
    agent_id: str,
    file: UploadFile = File(...),
    agent_repo: AgentRepository = Depends(get_agent_repo),
    source_repo: SourceRepository = Depends(get_source_repo),
    status_service: AgentStatusService = Depends(get_status_service),
    settings: Settings = Depends(get_settings),
) -> AgentPublic:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    data = await file.read()
    try:
        rel = save_avatar_upload(
            settings.workspace_path,
            agent_id,
            filename=file.filename,
            data=data,
        )
    except AgentAvatarError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    updated = await agent_repo.set_avatar(
        agent_id,
        avatar_path=rel,
        clear_preset=True,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await _public_agent(updated, source_repo, status_service)


@router.get("/agents/{agent_id}/avatar")
async def get_agent_avatar(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    path = find_avatar_file(settings.workspace_path, agent_id)
    if path is None and agent.avatar_path:
        candidate = (settings.workspace_path / agent.avatar_path).resolve()
        root = settings.workspace_path.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Avatar not found") from exc
        if candidate.is_file():
            path = candidate
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(path)


@router.delete("/agents/{agent_id}/avatar", response_model=AgentPublic)
async def delete_agent_avatar(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    source_repo: SourceRepository = Depends(get_source_repo),
    status_service: AgentStatusService = Depends(get_status_service),
    settings: Settings = Depends(get_settings),
) -> AgentPublic:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    clear_avatar_files(settings.workspace_path, agent_id)
    updated = await agent_repo.set_avatar(agent_id, clear_path=True)
    if updated is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await _public_agent(updated, source_repo, status_service)


@router.get("/agents/{agent_id}/status", response_model=AgentStatusInfo)
async def get_agent_status(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    status_service: AgentStatusService = Depends(get_status_service),
) -> AgentStatusInfo:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await status_service.get_status(agent)


@router.post("/agents/{agent_id}/status/refresh", response_model=AgentStatusInfo)
async def refresh_agent_status(
    agent_id: str,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    status_service: AgentStatusService = Depends(get_status_service),
) -> AgentStatusInfo:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await status_service.get_status(agent, force=True)


@router.post(
    "/agents/{agent_id}/run",
    response_model=RunAccepted,
    status_code=202,
)
async def run_agent(
    agent_id: str,
    request: Request,
    body: Optional[RunRequest] = None,
    agent_repo: AgentRepository = Depends(get_agent_repo),
    runner: AgentRunner = Depends(get_runner),
) -> RunAccepted:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    prompt = body.prompt if body else None
    try:
        log = await runner.start_run(
            agent_id,
            trigger_type=TriggerType.manual,
            prompt=prompt,
        )
    except AgentAlreadyRunningError as exc:
        raise HTTPException(
            status_code=409,
            detail="Agent already has a running execution",
        ) from exc

    if log is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    request.app.state.task_registry.create_task(
        runner.execute(log.id),
        name=f"manual-run-{log.id}",
    )
    return RunAccepted(execution_id=log.id)


@router.get("/agents/{agent_id}/logs", response_model=list[ExecutionLog])
async def list_agent_logs(
    agent_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    agent_repo: AgentRepository = Depends(get_agent_repo),
    execution_repo: ExecutionRepository = Depends(get_execution_repo),
) -> list[ExecutionLog]:
    agent = await agent_repo.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return await execution_repo.list_for_agent(agent_id, limit=limit)
