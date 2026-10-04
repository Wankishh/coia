"""Coia Agents harness — FastAPI entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from app.api import (
    activity,
    agents,
    chats,
    executions,
    health,
    providers,
    sources,
    usage,
)
from app.config import get_settings
from app.scheduler import AgentScheduler
from app.services.activity_registry import ActivityRegistry
from app.services.agent_runner import AgentRunner
from app.services.chat_service import ChatService
from app.services.demo_source import ensure_demo_source
from app.services.repos import (
    AgentRepository,
    ConversationRepository,
    ExecutionRepository,
    SourceRepository,
    UsageRepository,
)
from app.services.task_registry import TaskRegistry

ADMIN_STATIC_DIR = Path(__file__).resolve().parent / "static" / "admin"


class AdminStaticFiles(StaticFiles):
    """Serve admin assets; fall back to index.html for SPA path routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not self.html:
                raise
            # Nested paths like /admin/chat/... have no file; serve the SPA shell.
            return await super().get_response("index.html", scope)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("coia")

SHUTDOWN_TASK_TIMEOUT_SECONDS = 30.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.workspace_path.mkdir(parents=True, exist_ok=True)

    mongo = AsyncIOMotorClient(settings.mongodb_url)
    db = mongo[settings.mongodb_db]

    agent_repo = AgentRepository(db)
    source_repo = SourceRepository(db)
    execution_repo = ExecutionRepository(db)
    conversation_repo = ConversationRepository(db)
    usage_repo = UsageRepository(db)
    activity_registry = ActivityRegistry()
    chat_service = ChatService(
        agent_repo,
        conversation_repo,
        settings,
        source_repo,
        activity_registry,
        usage_repo,
    )
    runner = AgentRunner(
        agent_repo,
        execution_repo,
        settings,
        source_repo,
        chat_service,
        activity_registry,
        usage_repo,
    )
    task_registry = TaskRegistry()

    async def post_stuck_run_to_chat(execution_id: str) -> None:
        try:
            log = await execution_repo.get(execution_id)
            if log is not None:
                await chat_service.post_run_result(log)
        except Exception:  # noqa: BLE001 — chat notification is best-effort
            logger.warning(
                "Failed to post stuck execution %s to Agent runs chat",
                execution_id,
                exc_info=True,
            )

    scheduler = AgentScheduler(
        agent_repo,
        execution_repo,
        runner,
        task_registry,
        activity=activity_registry,
        stuck_threshold_seconds=settings.run_stuck_seconds,
        stuck_sweep_interval_seconds=settings.stuck_sweep_interval_seconds,
        on_stuck_failed=post_stuck_run_to_chat,
    )

    app.state.settings = settings
    app.state.mongo = mongo
    app.state.db = db
    app.state.agent_repo = agent_repo
    app.state.source_repo = source_repo
    app.state.execution_repo = execution_repo
    app.state.conversation_repo = conversation_repo
    app.state.usage_repo = usage_repo
    app.state.activity = activity_registry
    app.state.chat_service = chat_service
    app.state.runner = runner
    app.state.task_registry = task_registry
    app.state.scheduler = scheduler

    await db["agents"].create_index("id", unique=True)
    await source_repo.ensure_indexes()
    await execution_repo.ensure_indexes()
    await conversation_repo.ensure_indexes()
    await usage_repo.ensure_indexes()

    try:
        demo_source = await ensure_demo_source(source_repo, settings)
        if demo_source is not None:
            logger.info(
                "Demo data source ready id=%s title=%r",
                demo_source.id,
                demo_source.title,
            )
    except Exception:  # noqa: BLE001 — harness should still start without demo source
        logger.exception("Failed to auto-register demo data source")

    # Clear stale running docs from a previous process before accepting new jobs.
    interrupted = await execution_repo.fail_all_running("Interrupted by restart")
    if interrupted:
        logger.warning("Marked %d interrupted running execution(s) as failed", interrupted)

    scheduler.start()
    await scheduler.reload_all()
    logger.info(
        "Coia Agents harness ready (mongo_db=%s workspace=%s)",
        settings.mongodb_db,
        settings.workspace_path,
    )

    try:
        yield
    finally:
        scheduler.shutdown()
        await task_registry.wait_shutdown(timeout=SHUTDOWN_TASK_TIMEOUT_SECONDS)
        remaining = await execution_repo.fail_all_running("Interrupted by restart")
        if remaining:
            logger.warning(
                "Force-failed %d still-running execution(s) on shutdown", remaining
            )
        mongo.close()
        logger.info("Coia Agents harness shut down")


app = FastAPI(
    title="Coia Agents",
    description="Monolithic agent harness: FastAPI + LangGraph + APScheduler + MongoDB",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(agents.router)
app.include_router(chats.router)
app.include_router(sources.router)
app.include_router(executions.router)
app.include_router(activity.router)
app.include_router(providers.router)
app.include_router(usage.router)


@app.get("/admin", include_in_schema=False)
async def admin_redirect() -> RedirectResponse:
    return RedirectResponse(url="/admin/", status_code=307)


app.mount(
    "/admin",
    AdminStaticFiles(directory=str(ADMIN_STATIC_DIR), html=True),
    name="admin",
)
