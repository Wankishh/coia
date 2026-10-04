"""Per-agent connection / readiness status (lightweight provider probes)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from pydantic import BaseModel

from app.models.agent import (
    STATUS_LABELS,
    AgentConfig,
    AgentConnectionStatus,
    LLMProvider,
)
from app.models.execution import ExecutionLog, ExecutionStatus
from app.services.llm_factory import resolve_ollama_base_url
from app.services.repos import ExecutionRepository

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_SECONDS = 6.0
STATUS_CACHE_TTL_SECONDS = 60.0
RECENT_FAILURE_WINDOW = timedelta(hours=24)

OPENROUTER_KEY_URL = "https://openrouter.ai/api/v1/key"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
GOOGLE_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentStatusInfo(BaseModel):
    status: AgentConnectionStatus
    status_label: str
    error_message: Optional[str] = None
    checked_at: Optional[datetime] = None

    @classmethod
    def make(
        cls,
        status: AgentConnectionStatus,
        *,
        error_message: Optional[str] = None,
        checked_at: Optional[datetime] = None,
    ) -> AgentStatusInfo:
        return cls(
            status=status,
            status_label=STATUS_LABELS[status],
            error_message=error_message,
            checked_at=checked_at,
        )


# agent_id -> (expires_at_monotonic, AgentStatusInfo)
_status_cache: dict[str, tuple[float, AgentStatusInfo]] = {}


def clear_status_cache(agent_id: Optional[str] = None) -> None:
    """Clear cached status for one agent, or all agents."""
    if agent_id is None:
        _status_cache.clear()
    else:
        _status_cache.pop(agent_id, None)


def _truncate_error(message: str, limit: int = 500) -> str:
    text = " ".join(message.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _parse_provider_error(response: httpx.Response) -> str:
    """Extract a human-readable message from a provider error body."""
    status = response.status_code
    body: Any = None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        text = (response.text or "").strip()
        if text:
            return _truncate_error(f"HTTP {status}: {text}")
        return f"HTTP {status}"

    detail: Optional[str] = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            detail = err.get("message") or err.get("type") or str(err)
        elif isinstance(err, str):
            detail = err
        elif body.get("message"):
            detail = str(body["message"])
        elif body.get("detail"):
            detail = str(body["detail"])

    if status in (401, 403):
        base = "Invalid API key or unauthorized"
    elif status == 429:
        base = "Provider rate limit exceeded"
    elif status >= 500:
        base = "Provider server error"
    else:
        base = f"Provider HTTP {status}"

    if detail:
        return _truncate_error(f"{base}: {detail}")
    return base


async def _probe_openai(api_key: str) -> None:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        resp = await client.get(OPENAI_MODELS_URL, headers=headers)
        if resp.status_code >= 400:
            raise ValueError(_parse_provider_error(resp))


async def _probe_anthropic(api_key: str) -> None:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        resp = await client.get(ANTHROPIC_MODELS_URL, headers=headers)
        if resp.status_code >= 400:
            raise ValueError(_parse_provider_error(resp))


async def _probe_google(api_key: str) -> None:
    params = {"key": api_key}
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        resp = await client.get(GOOGLE_MODELS_URL, params=params)
        if resp.status_code >= 400:
            raise ValueError(_parse_provider_error(resp))


async def _probe_openrouter(api_key: str) -> None:
    # models.list works without a key; /key validates the credential.
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        resp = await client.get(OPENROUTER_KEY_URL, headers=headers)
        if resp.status_code >= 400:
            raise ValueError(_parse_provider_error(resp))


async def _probe_ollama(base_url: Optional[str] = None) -> None:
    """Reachability probe — no API key required."""
    resolved = resolve_ollama_base_url(base_url)
    headers = {"Accept": "application/json"}
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        resp = await client.get(f"{resolved}/models", headers=headers)
        if resp.status_code < 400:
            return
        root = resolved.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")].rstrip("/")
        resp2 = await client.get(f"{root}/api/tags", headers=headers)
        if resp2.status_code >= 400:
            raise ValueError(_parse_provider_error(resp2))


async def probe_provider(
    provider: LLMProvider,
    api_key: str = "",
    *,
    base_url: Optional[str] = None,
) -> None:
    """Raise ValueError with a human-readable message if the probe fails."""
    key = (api_key or "").strip()
    if provider == LLMProvider.openai:
        await _probe_openai(key)
    elif provider == LLMProvider.anthropic:
        await _probe_anthropic(key)
    elif provider == LLMProvider.google:
        await _probe_google(key)
    elif provider == LLMProvider.openrouter:
        await _probe_openrouter(key)
    elif provider == LLMProvider.ollama:
        await _probe_ollama(base_url)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def _recent_failure_message(log: Optional[ExecutionLog]) -> Optional[str]:
    if log is None or log.status != ExecutionStatus.failed:
        return None
    end = log.end_time or log.start_time
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if _utcnow() - end > RECENT_FAILURE_WINDOW:
        return None
    msg = (log.error_message or "").strip() or "Last run failed"
    return _truncate_error(msg)


class AgentStatusService:
    """Compute readiness status for agents with a short in-memory cache."""

    def __init__(self, execution_repo: ExecutionRepository) -> None:
        self._executions = execution_repo

    async def get_status(
        self,
        agent: AgentConfig,
        *,
        force: bool = False,
    ) -> AgentStatusInfo:
        agent_id = agent.id
        now_mono = time.monotonic()

        if not force:
            cached = _status_cache.get(agent_id)
            if cached and cached[0] > now_mono:
                # Running may change while cache is warm — re-check that flag.
                if await self._executions.has_running(agent_id):
                    return AgentStatusInfo.make(
                        AgentConnectionStatus.running,
                        checked_at=cached[1].checked_at or _utcnow(),
                    )
                if cached[1].status != AgentConnectionStatus.running:
                    return cached[1]

        info = await self._compute_status(agent)
        _status_cache[agent_id] = (now_mono + STATUS_CACHE_TTL_SECONDS, info)
        return info

    async def get_status_many(
        self,
        agents: list[AgentConfig],
        *,
        force: bool = False,
    ) -> dict[str, AgentStatusInfo]:
        if not agents:
            return {}
        results = await asyncio.gather(
            *(self.get_status(a, force=force) for a in agents),
            return_exceptions=True,
        )
        out: dict[str, AgentStatusInfo] = {}
        for agent, result in zip(agents, results):
            if isinstance(result, AgentStatusInfo):
                out[agent.id] = result
            else:
                logger.warning(
                    "Status check failed for agent %s: %s",
                    agent.id,
                    result,
                )
                out[agent.id] = AgentStatusInfo.make(
                    AgentConnectionStatus.error,
                    error_message=_truncate_error(
                        str(result) or "Status check failed"
                    ),
                    checked_at=_utcnow(),
                )
        return out

    async def _compute_status(self, agent: AgentConfig) -> AgentStatusInfo:
        checked_at = _utcnow()
        key = (agent.api_key or "").strip()
        is_ollama = agent.provider == LLMProvider.ollama
        # Ollama is local — no key required; probe reachability instead.
        if not key and not is_ollama:
            return AgentStatusInfo.make(
                AgentConnectionStatus.not_configured,
                checked_at=checked_at,
            )

        if await self._executions.has_running(agent.id):
            return AgentStatusInfo.make(
                AgentConnectionStatus.running,
                checked_at=checked_at,
            )

        recent_failed = await self._executions.get_latest_failed(agent.id)
        failure_msg = _recent_failure_message(recent_failed)

        try:
            await asyncio.wait_for(
                probe_provider(
                    agent.provider,
                    key,
                    base_url=agent.base_url,
                ),
                timeout=PROBE_TIMEOUT_SECONDS + 1.0,
            )
        except asyncio.TimeoutError:
            msg = "Provider check timed out"
            if failure_msg:
                msg = f"{msg}. Last run error: {failure_msg}"
            return AgentStatusInfo.make(
                AgentConnectionStatus.error,
                error_message=msg,
                checked_at=checked_at,
            )
        except httpx.TimeoutException:
            msg = "Provider check timed out"
            if failure_msg:
                msg = f"{msg}. Last run error: {failure_msg}"
            return AgentStatusInfo.make(
                AgentConnectionStatus.error,
                error_message=msg,
                checked_at=checked_at,
            )
        except httpx.RequestError as exc:
            # Never include request headers/URL query (Google key is in query).
            msg = f"Provider unreachable: {exc.__class__.__name__}"
            if failure_msg:
                msg = f"{msg}. Last run error: {failure_msg}"
            return AgentStatusInfo.make(
                AgentConnectionStatus.error,
                error_message=_truncate_error(msg),
                checked_at=checked_at,
            )
        except ValueError as exc:
            msg = str(exc) or "Provider check failed"
            if failure_msg and failure_msg not in msg:
                msg = f"{msg}. Last run error: {failure_msg}"
            return AgentStatusInfo.make(
                AgentConnectionStatus.error,
                error_message=_truncate_error(msg),
                checked_at=checked_at,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Unexpected probe error for agent %s (%s)",
                agent.id,
                type(exc).__name__,
            )
            msg = "Provider check failed"
            if failure_msg:
                msg = f"{msg}. Last run error: {failure_msg}"
            return AgentStatusInfo.make(
                AgentConnectionStatus.error,
                error_message=msg,
                checked_at=checked_at,
            )

        return AgentStatusInfo.make(
            AgentConnectionStatus.ready,
            checked_at=checked_at,
        )
