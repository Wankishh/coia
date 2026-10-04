"""Agent configuration models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Self
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.source import SourceConfig, SourceSummary, to_source_summary


class LLMProvider(str, Enum):
    openai = "openai"
    anthropic = "anthropic"
    google = "google"
    openrouter = "openrouter"
    ollama = "ollama"


def _normalize_optional_url(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    url = value.strip()
    return url or None


class AgentConnectionStatus(str, Enum):
    not_configured = "not_configured"
    ready = "ready"
    error = "error"
    running = "running"


STATUS_LABELS: dict[AgentConnectionStatus, str] = {
    AgentConnectionStatus.not_configured: "Not configured",
    AgentConnectionStatus.ready: "Ready",
    AgentConnectionStatus.error: "Error",
    AgentConnectionStatus.running: "Running",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Cap middle stars so long keys stay readable in the UI.
_API_KEY_PREVIEW_MAX_STARS = 12


def mask_api_key(key: Optional[str]) -> Optional[str]:
    """
    Build a masked preview of an API key for public responses.

    Never returns the full key. Empty / missing → None.
    Short keys (≤8) expose first/last 1–2 chars with the middle starred.
    Longer keys: first 4 + up to 12 stars + last 4.
    """
    if key is None:
        return None
    value = key.strip()
    if not value:
        return None

    n = len(value)
    if n <= 2:
        # Tiny secrets: show ends only if possible, else all stars.
        if n == 1:
            return "*"
        return value[0] + "*"
    if n <= 8:
        # Show first 2 + last 2 when length allows; otherwise first/last 1.
        head = 2 if n >= 4 else 1
        tail = 2 if n >= 4 else 1
        middle = max(n - head - tail, 1)
        return value[:head] + ("*" * middle) + value[-tail:]

    stars = min(n - 8, _API_KEY_PREVIEW_MAX_STARS)
    return value[:4] + ("*" * stars) + value[-4:]


class AgentCreate(BaseModel):
    name: str
    role: str
    system_prompt: str
    provider: LLMProvider
    model_name: str
    # Required for cloud providers; optional/empty for ollama (local).
    api_key: str = ""
    # Optional OpenAI-compatible endpoint override (meaningful for ollama).
    base_url: Optional[str] = None
    enabled_tools: list[str] = Field(default_factory=list)
    cron_schedule: Optional[str] = None
    # When True, cron jobs are unscheduled; schedule string is kept for resume.
    paused: bool = False
    default_prompt: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)
    # Legacy: embedded full source blobs (accepted briefly for compat).
    sources: list[SourceConfig] = Field(default_factory=list)
    # Preset id (moss/signal/sky/coral/violet/sand); image via upload endpoint.
    avatar_preset: Optional[str] = None
    # Optional peer agent to receive HTML report handoffs.
    handoff_agent_id: Optional[str] = None

    @field_validator("api_key", mode="before")
    @classmethod
    def coerce_api_key(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_url(value)

    @model_validator(mode="after")
    def api_key_required_unless_ollama(self) -> Self:
        if self.provider != LLMProvider.ollama and not self.api_key:
            raise ValueError("api_key is required")
        return self


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    system_prompt: Optional[str] = None
    provider: Optional[LLMProvider] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    enabled_tools: Optional[list[str]] = None
    cron_schedule: Optional[str] = None
    paused: Optional[bool] = None
    default_prompt: Optional[str] = None
    source_ids: Optional[list[str]] = None
    # Legacy: embedded full source blobs (accepted briefly for compat).
    sources: Optional[list[SourceConfig]] = None
    avatar_preset: Optional[str] = None
    handoff_agent_id: Optional[str] = None

    @field_validator("api_key")
    @classmethod
    def api_key_non_empty_when_set(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        key = value.strip()
        if not key:
            raise ValueError("api_key cannot be empty when provided")
        return key

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: Optional[str]) -> Optional[str]:
        return _normalize_optional_url(value)


class AgentConfig(BaseModel):
    """Internal / stored agent document (includes api_key)."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    role: str
    system_prompt: str
    provider: LLMProvider
    model_name: str
    api_key: str = ""
    # Optional OpenAI-compatible endpoint override (meaningful for ollama).
    base_url: Optional[str] = None
    enabled_tools: list[str] = Field(default_factory=list)
    cron_schedule: Optional[str] = None
    # Missing/false in stored docs = active (cron may run if scheduled).
    paused: bool = False
    default_prompt: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)
    # Legacy embedded sources — prefer source_ids when present.
    sources: list[SourceConfig] = Field(default_factory=list)
    # Preset style id; uploaded image path under workspace/_avatars/{id}/…
    avatar_preset: Optional[str] = None
    avatar_path: Optional[str] = None
    handoff_agent_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class AgentPublic(BaseModel):
    """API response shape — never echoes the raw api_key."""

    id: str
    name: str
    role: str
    system_prompt: str
    provider: LLMProvider
    model_name: str
    api_key_set: bool
    api_key_preview: Optional[str] = None
    base_url: Optional[str] = None
    enabled_tools: list[str] = Field(default_factory=list)
    cron_schedule: Optional[str] = None
    paused: bool = False
    default_prompt: Optional[str] = None
    source_ids: list[str] = Field(default_factory=list)
    sources: list[SourceSummary] = Field(default_factory=list)
    avatar_preset: Optional[str] = None
    avatar_url: Optional[str] = None
    handoff_agent_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Connection / readiness (enriched by API; defaults for unset callers).
    status: AgentConnectionStatus = AgentConnectionStatus.not_configured
    status_label: str = "Not configured"
    error_message: Optional[str] = None
    checked_at: Optional[datetime] = None


def to_public(
    agent: AgentConfig,
    *,
    resolved_sources: Optional[list[SourceConfig]] = None,
    status: Optional[AgentConnectionStatus] = None,
    status_label: Optional[str] = None,
    error_message: Optional[str] = None,
    checked_at: Optional[datetime] = None,
) -> AgentPublic:
    """
    Build public agent view.

    Prefer resolved library sources when provided. If `source_ids` is set on the
    agent, those ids are returned even when some library docs are missing.
    """
    if resolved_sources is not None:
        summaries = [to_source_summary(s) for s in resolved_sources]
    elif agent.source_ids:
        # Caller should resolve; fall back to empty summaries from ids only.
        summaries = []
    else:
        summaries = [to_source_summary(s) for s in agent.sources]

    source_ids = list(agent.source_ids) if agent.source_ids else [s.id for s in summaries]

    conn_status = status or AgentConnectionStatus.not_configured
    label = status_label or STATUS_LABELS[conn_status]
    preview = mask_api_key(agent.api_key)

    avatar_url = (
        f"/agents/{agent.id}/avatar" if agent.avatar_path else None
    )

    return AgentPublic(
        id=agent.id,
        name=agent.name,
        role=agent.role,
        system_prompt=agent.system_prompt,
        provider=agent.provider,
        model_name=agent.model_name,
        api_key_set=preview is not None,
        api_key_preview=preview,
        base_url=agent.base_url,
        enabled_tools=agent.enabled_tools,
        cron_schedule=agent.cron_schedule,
        paused=bool(agent.paused),
        default_prompt=agent.default_prompt,
        source_ids=source_ids,
        sources=summaries,
        avatar_preset=agent.avatar_preset,
        avatar_url=avatar_url,
        handoff_agent_id=agent.handoff_agent_id,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        status=conn_status,
        status_label=label,
        error_message=error_message,
        checked_at=checked_at,
    )
