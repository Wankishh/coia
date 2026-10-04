"""Quick checks for prompt placeholder interpolation."""

from __future__ import annotations

from types import SimpleNamespace

from app.models.agent import LLMProvider
from app.services.prompt_interpolate import interpolate_prompt


def test_interpolates_all_placeholders() -> None:
    agent = SimpleNamespace(
        name="Josh",
        role="financial_analyst",
        model_name="gpt-4o",
        provider=LLMProvider.openai,
    )
    text = (
        "You are {{name}} ({{agent_name}}), role={{role}}, "
        "via {{provider}} / {{model}} ({{model_name}})."
    )
    assert interpolate_prompt(text, agent) == (
        "You are Josh (Josh), role=financial_analyst, "
        "via openai / gpt-4o (gpt-4o)."
    )


def test_flexible_name_and_role_tokens() -> None:
    agent = SimpleNamespace(
        name="Josh",
        role="financial_analyst",
        model_name="gpt-4o",
        provider=LLMProvider.openai,
    )
    assert interpolate_prompt("{{ Name }} / {{NAME}} / {{agent_name}}", agent) == (
        "Josh / Josh / Josh"
    )
    assert interpolate_prompt("{{ role }} / {{Role}} / {{ROLE}}", agent) == (
        "financial_analyst / financial_analyst / financial_analyst"
    )


def test_leaves_unknown_and_handles_empty() -> None:
    agent = SimpleNamespace(
        name="Ada",
        role="ops",
        model_name="m",
        provider="openrouter",
    )
    assert interpolate_prompt("Hi {{name}} {{unknown}}", agent) == "Hi Ada {{unknown}}"
    assert interpolate_prompt(None, agent) == ""
    assert interpolate_prompt("", agent) == ""


if __name__ == "__main__":
    test_interpolates_all_placeholders()
    test_flexible_name_and_role_tokens()
    test_leaves_unknown_and_handles_empty()
    print("ok")
