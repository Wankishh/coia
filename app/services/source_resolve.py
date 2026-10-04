"""Resolve agent-attached sources from the library (with legacy fallback)."""

from __future__ import annotations

from app.models.agent import AgentConfig
from app.models.source import SourceConfig
from app.services.repos import SourceRepository


async def resolve_agent_sources(
    agent: AgentConfig,
    source_repo: SourceRepository,
) -> list[SourceConfig]:
    """
    Prefer `source_ids` → library docs. Fall back to embedded `sources[]`
    for agents that have not been migrated yet.
    """
    if agent.source_ids:
        docs = await source_repo.get_many(agent.source_ids)
        return [doc.as_source_config() for doc in docs]
    return list(agent.sources)
