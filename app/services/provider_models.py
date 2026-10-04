"""Fetch and cache LLM model lists from provider APIs."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.models.agent import LLMProvider
from app.services.llm_factory import resolve_ollama_base_url

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 15 * 60  # 15 minutes for successful live fetches
FALLBACK_CACHE_TTL_SECONDS = 60  # shorter so a corrected api_key can retry soon
HTTP_TIMEOUT_SECONDS = 20.0

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
GOOGLE_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str


FALLBACK_MODELS: dict[LLMProvider, list[ModelInfo]] = {
    # Verified against provider docs + OpenRouter catalog (2026-10).
    LLMProvider.openai: [
        ModelInfo("gpt-6-astra", "gpt-6-astra"),
        ModelInfo("gpt-6.1-sol", "gpt-6.1-sol"),
        ModelInfo("gpt-6-luna", "gpt-6-luna"),
        ModelInfo("gpt-5", "gpt-5"),
        ModelInfo("gpt-5-mini", "gpt-5-mini"),
        ModelInfo("gpt-4.1", "gpt-4.1"),
        ModelInfo("gpt-4o", "gpt-4o"),
        ModelInfo("gpt-4o-mini", "gpt-4o-mini"),
        ModelInfo("o3", "o3"),
        ModelInfo("o4-mini", "o4-mini"),
    ],
    LLMProvider.anthropic: [
        ModelInfo("claude-fable-5-1", "claude-fable-5-1"),
        ModelInfo("claude-opus-5-5", "claude-opus-5-5"),
        ModelInfo("claude-sonnet-5-5", "claude-sonnet-5-5"),
        ModelInfo("claude-haiku-4-5", "claude-haiku-4-5"),
        ModelInfo("claude-opus-5", "claude-opus-5"),
        ModelInfo("claude-sonnet-5", "claude-sonnet-5"),
        ModelInfo("claude-opus-4-8", "claude-opus-4-8"),
        ModelInfo("claude-sonnet-4-6", "claude-sonnet-4-6"),
    ],
    LLMProvider.google: [
        ModelInfo("gemini-3.8-flash", "gemini-3.8-flash"),
        ModelInfo("gemini-3.7-flash", "gemini-3.7-flash"),
        ModelInfo("gemini-3.6-flash", "gemini-3.6-flash"),
        ModelInfo("gemini-3.5-flash", "gemini-3.5-flash"),
        ModelInfo("gemini-3.5-flash-lite", "gemini-3.5-flash-lite"),
        ModelInfo("gemini-3.1-pro-preview", "gemini-3.1-pro-preview"),
        ModelInfo("gemini-2.5-pro", "gemini-2.5-pro"),
        ModelInfo("gemini-2.5-flash", "gemini-2.5-flash"),
        ModelInfo("gemini-2.5-flash-lite", "gemini-2.5-flash-lite"),
    ],
    LLMProvider.openrouter: [
        ModelInfo("openai/gpt-6-astra", "openai/gpt-6-astra"),
        ModelInfo("openai/gpt-5", "openai/gpt-5"),
        ModelInfo("openai/gpt-4.1", "openai/gpt-4.1"),
        ModelInfo("openai/gpt-4o", "openai/gpt-4o"),
        ModelInfo("anthropic/claude-sonnet-5.5", "anthropic/claude-sonnet-5.5"),
        ModelInfo("anthropic/claude-opus-5.5", "anthropic/claude-opus-5.5"),
        ModelInfo("google/gemini-3.8-flash", "google/gemini-3.8-flash"),
        ModelInfo("google/gemini-2.5-pro", "google/gemini-2.5-pro"),
        ModelInfo("meta-llama/llama-3.3-70b-instruct", "meta-llama/llama-3.3-70b-instruct"),
    ],
    LLMProvider.ollama: [
        ModelInfo("llama3.2", "llama3.2"),
        ModelInfo("mistral", "mistral"),
        ModelInfo("qwen2.5", "qwen2.5"),
    ],
}

# In-memory cache: key -> (expires_at, models, source)
_cache: dict[str, tuple[float, list[ModelInfo], str]] = {}


def _cache_key(
    provider: LLMProvider,
    has_key: bool,
    base_url: Optional[str] = None,
) -> str:
    if provider == LLMProvider.ollama:
        return f"{provider.value}:{base_url or 'default'}"
    return f"{provider.value}:{'key' if has_key else 'nokey'}"


def _sort_models(models: list[ModelInfo]) -> list[ModelInfo]:
    return sorted(models, key=lambda m: m.name.lower())


def _dedupe(models: list[ModelInfo]) -> list[ModelInfo]:
    seen: set[str] = set()
    out: list[ModelInfo] = []
    for m in models:
        if m.id in seen:
            continue
        seen.add(m.id)
        out.append(m)
    return out


def _is_openai_chat_model(model_id: str) -> bool:
    mid = model_id.lower()
    # Exclude obvious non-chat / non-completion endpoints.
    exclude_prefixes = (
        "text-embedding",
        "text-moderation",
        "tts-",
        "whisper-",
        "dall-e",
        "davinci",
        "babbage",
        "curie",
        "ada",
        "chatgpt-image",
        "omni-moderation",
        "sora-",
    )
    if any(mid.startswith(p) for p in exclude_prefixes):
        return False
    # Chat / reasoning families: gpt-*, chatgpt-*, o-series (o1, o3, o4, …).
    # Keep fine-tunes and aliases that contain "gpt". Avoid dropping newer
    # flagship ids (gpt-5 / gpt-6 / …) that still use the gpt- prefix.
    if mid.startswith("gpt-") or mid.startswith("chatgpt-") or "gpt" in mid:
        return True
    # o-series: o1, o3-mini, o4-mini, future o5*, …
    if len(mid) >= 2 and mid[0] == "o" and mid[1].isdigit():
        return True
    return False


async def _fetch_openrouter(api_key: Optional[str]) -> list[ModelInfo]:
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.get(OPENROUTER_MODELS_URL, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    models: list[ModelInfo] = []
    for item in data.get("data") or []:
        mid = item.get("id")
        if not mid:
            continue
        name = item.get("name") or mid
        models.append(ModelInfo(id=mid, name=name))
    return _sort_models(_dedupe(models))


async def _fetch_openai(api_key: str) -> list[ModelInfo]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.get(OPENAI_MODELS_URL, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    models: list[ModelInfo] = []
    for item in data.get("data") or []:
        mid = item.get("id")
        if not mid or not _is_openai_chat_model(mid):
            continue
        models.append(ModelInfo(id=mid, name=mid))
    return _sort_models(_dedupe(models))


async def _fetch_anthropic(api_key: str) -> list[ModelInfo]:
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.get(ANTHROPIC_MODELS_URL, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    models: list[ModelInfo] = []
    for item in data.get("data") or []:
        mid = item.get("id")
        if not mid:
            continue
        name = item.get("display_name") or mid
        models.append(ModelInfo(id=mid, name=name))
    return _sort_models(_dedupe(models))


async def _fetch_google(api_key: str) -> list[ModelInfo]:
    params = {"key": api_key}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.get(GOOGLE_MODELS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    models: list[ModelInfo] = []
    for item in data.get("models") or []:
        name = item.get("name") or ""
        # API returns "models/gemini-1.5-pro"; store bare id for ChatGoogleGenerativeAI.
        mid = name.split("/", 1)[-1] if name else ""
        if not mid:
            continue
        methods = item.get("supportedGenerationMethods") or []
        if methods and "generateContent" not in methods:
            continue
        display = item.get("displayName") or mid
        models.append(ModelInfo(id=mid, name=display))
    return _sort_models(_dedupe(models))


def _ollama_native_root(base_url: str) -> str:
    """Strip trailing /v1 from OpenAI-compat base for native /api/tags."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root.rstrip("/")


async def _fetch_ollama(
    api_key: Optional[str],
    base_url: Optional[str] = None,
) -> list[ModelInfo]:
    """
    List local Ollama models.

    Prefer OpenAI-compatible ``GET {base}/models``; fall back to native
    ``GET {root}/api/tags``. API key is optional.
    """
    resolved = resolve_ollama_base_url(base_url)
    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        # 1) OpenAI-compatible /v1/models
        try:
            resp = await client.get(f"{resolved}/models", headers=headers)
            if resp.status_code < 400:
                data = resp.json()
                models: list[ModelInfo] = []
                for item in data.get("data") or []:
                    mid = item.get("id")
                    if not mid:
                        continue
                    name = item.get("name") or mid
                    models.append(ModelInfo(id=mid, name=name))
                if models:
                    return _sort_models(_dedupe(models))
        except httpx.HTTPError:
            pass

        # 2) Native Ollama tags
        root = _ollama_native_root(resolved)
        resp = await client.get(f"{root}/api/tags", headers=headers)
        resp.raise_for_status()
        data = resp.json()

    models = []
    for item in data.get("models") or []:
        # tags API: { name, model, … }; prefer bare model name for chat ids.
        mid = item.get("model") or item.get("name")
        if not mid:
            continue
        # Drop :latest noise when identical; keep tag when non-default.
        name = item.get("name") or mid
        models.append(ModelInfo(id=mid, name=name))
    return _sort_models(_dedupe(models))


async def list_provider_models(
    provider: LLMProvider,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> dict[str, Any]:
    """
    Return {"models": [{"id","name"}], "source": "live"|"fallback"}.

    OpenRouter and Ollama can list without a key. OpenAI / Anthropic / Google
    need a key for a live list; without one (or on failure) we return a static
    fallback. Optional ``base_url`` is used for ollama (live list before save).
    """
    key = (api_key or "").strip() or None
    resolved_base: Optional[str] = None
    if provider == LLMProvider.ollama:
        # Include settings default in the cache key so env changes refresh.
        resolved_base = resolve_ollama_base_url(base_url)
    cache_k = _cache_key(provider, bool(key), resolved_base)
    now = time.monotonic()
    cached = _cache.get(cache_k)
    if cached and cached[0] > now:
        models, source = cached[1], cached[2]
        return {
            "models": [{"id": m.id, "name": m.name} for m in models],
            "source": source,
        }

    source = "live"
    models: list[ModelInfo] = []

    try:
        if provider == LLMProvider.openrouter:
            models = await _fetch_openrouter(key)
        elif provider == LLMProvider.openai:
            if not key:
                raise ValueError("OpenAI model list requires an api_key")
            models = await _fetch_openai(key)
        elif provider == LLMProvider.anthropic:
            if not key:
                raise ValueError("Anthropic model list requires an api_key")
            models = await _fetch_anthropic(key)
        elif provider == LLMProvider.google:
            if not key:
                raise ValueError("Google model list requires an api_key")
            models = await _fetch_google(key)
        elif provider == LLMProvider.ollama:
            models = await _fetch_ollama(key, base_url=base_url)
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        if not models:
            raise ValueError("Provider returned an empty model list")
    except Exception as exc:
        logger.warning(
            "Live model fetch failed for %s (%s); using fallback",
            provider.value,
            exc,
        )
        models = list(FALLBACK_MODELS.get(provider, []))
        source = "fallback"

    ttl = CACHE_TTL_SECONDS if source == "live" else FALLBACK_CACHE_TTL_SECONDS
    _cache[cache_k] = (now + ttl, models, source)
    return {
        "models": [{"id": m.id, "name": m.name} for m in models],
        "source": source,
    }


def clear_model_cache() -> None:
    """Test helper."""
    _cache.clear()
