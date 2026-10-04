"""Interpolate agent persona fields into prompt templates before LLM calls.

Supported placeholders (token name is case-insensitive; whitespace inside
``{{ … }}`` is optional):

- ``{{name}}`` / ``{{agent_name}}`` → agent.name (display / persona name)
- ``{{role}}`` → agent.role
- ``{{model}}`` / ``{{model_name}}`` → agent.model_name
- ``{{provider}}`` → agent.provider

Examples that all resolve to the same fields: ``{{name}}``, ``{{ Name }}``,
``{{NAME}}``, ``{{agent_name}}``, ``{{role}}``, ``{{ Role }}``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

__all__ = ["interpolate_prompt", "PROMPT_PLACEHOLDERS"]

PROMPT_PLACEHOLDERS = (
    "{{name}}",
    "{{agent_name}}",
    "{{role}}",
    "{{model}}",
    "{{model_name}}",
    "{{provider}}",
)

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# Canonical field keyed by lowercased token name.
_TOKEN_ALIASES = {
    "name": "name",
    "agent_name": "name",
    "role": "role",
    "model": "model",
    "model_name": "model",
    "provider": "provider",
}


def interpolate_prompt(text: Optional[str], agent: Any) -> str:
    """Replace ``{{…}}`` tokens in *text* using fields from *agent*."""
    if text is None:
        return ""
    if not text:
        return text

    name = str(getattr(agent, "name", "") or "")
    role = str(getattr(agent, "role", "") or "")
    model_name = str(getattr(agent, "model_name", "") or "")
    provider = getattr(agent, "provider", "")
    provider_str = provider.value if hasattr(provider, "value") else str(provider or "")

    values = {
        "name": name,
        "role": role,
        "model": model_name,
        "provider": provider_str,
    }

    def _replace(match: re.Match[str]) -> str:
        alias = _TOKEN_ALIASES.get(match.group(1).lower())
        if alias is None:
            return match.group(0)
        return values[alias]

    return _TOKEN_RE.sub(_replace, text)
