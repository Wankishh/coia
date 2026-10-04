"""FastAPI dependency helpers."""

from typing import Annotated

from fastapi import Request

from app.config import Settings
from app.scheduler import AgentScheduler
from app.services.agent_runner import AgentRunner
from app.services.agent_status import AgentStatusService
from app.services.chat_service import ChatService
from app.services.repos import (
    AgentRepository,
    ConversationRepository,
    ExecutionRepository,
    SourceRepository,
    UsageRepository,
)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_agent_repo(request: Request) -> AgentRepository:
    return request.app.state.agent_repo


def get_source_repo(request: Request) -> SourceRepository:
    return request.app.state.source_repo


def get_execution_repo(request: Request) -> ExecutionRepository:
    return request.app.state.execution_repo


def get_status_service(request: Request) -> AgentStatusService:
    cached = getattr(request.app.state, "status_service", None)
    if cached is not None:
        return cached
    service = AgentStatusService(request.app.state.execution_repo)
    request.app.state.status_service = service
    return service


def get_conversation_repo(request: Request) -> ConversationRepository:
    return request.app.state.conversation_repo


def get_chat_service(request: Request) -> ChatService:
    return request.app.state.chat_service


def get_usage_repo(request: Request) -> UsageRepository:
    return request.app.state.usage_repo


def get_runner(request: Request) -> AgentRunner:
    return request.app.state.runner


def get_scheduler(request: Request) -> AgentScheduler:
    return request.app.state.scheduler


SettingsDep = Annotated[Settings, ...]
AgentRepoDep = Annotated[AgentRepository, ...]
SourceRepoDep = Annotated[SourceRepository, ...]
ExecutionRepoDep = Annotated[ExecutionRepository, ...]
ConversationRepoDep = Annotated[ConversationRepository, ...]
ChatServiceDep = Annotated[ChatService, ...]
UsageRepoDep = Annotated[UsageRepository, ...]
RunnerDep = Annotated[AgentRunner, ...]
SchedulerDep = Annotated[AgentScheduler, ...]
