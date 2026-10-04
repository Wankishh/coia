"""Provider metadata endpoints (model lists, etc.)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query

from app.models.agent import LLMProvider
from app.services.provider_models import list_provider_models

router = APIRouter(tags=["providers"])


@router.get("/providers/{provider}/models")
async def get_provider_models(
    provider: str,
    api_key: Optional[str] = Query(
        None,
        description="Optional provider API key (also accepted via X-Api-Key header)",
    ),
    x_api_key: Optional[str] = Header(
        None,
        alias="X-Api-Key",
        description="Optional provider API key",
    ),
    base_url: Optional[str] = Query(
        None,
        description=(
            "Optional OpenAI-compatible base URL (ollama). "
            "Used for live model lists before the agent is saved."
        ),
    ),
) -> dict:
    """
    List models for a provider.

    Upstream sources:
    - openrouter: GET https://openrouter.ai/api/v1/models (key optional)
    - openai: GET https://api.openai.com/v1/models (key required for live)
    - anthropic: GET https://api.anthropic.com/v1/models (key required for live)
    - google: GET https://generativelanguage.googleapis.com/v1beta/models (key required)
    - ollama: GET {base}/models or {root}/api/tags (key optional; base_url optional)

    On network/API failure (or missing key when required), returns a small static
    fallback list with ``source: "fallback"``.
    """
    try:
        llm_provider = LLMProvider(provider.lower().strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown provider '{provider}'. "
                f"Expected one of: {', '.join(p.value for p in LLMProvider)}"
            ),
        ) from exc

    key = (api_key or x_api_key or "").strip() or None
    url = (base_url or "").strip() or None
    return await list_provider_models(
        llm_provider,
        api_key=key,
        base_url=url,
    )
