"""Agent pause field defaults and public mapping."""

from __future__ import annotations

from app.models.agent import AgentConfig, AgentPublic, LLMProvider, to_public


def _minimal_agent(**overrides) -> AgentConfig:
    data = {
        "name": "Josh",
        "role": "analyst",
        "system_prompt": "You are helpful.",
        "provider": LLMProvider.openai,
        "model_name": "gpt-4o",
        "api_key": "sk-test-key-12345678",
        "cron_schedule": "0 9 * * *",
    }
    data.update(overrides)
    return AgentConfig(**data)


def test_paused_defaults_false() -> None:
    agent = _minimal_agent()
    assert agent.paused is False


def test_legacy_doc_without_paused_field() -> None:
    """Existing Mongo docs omit paused; Pydantic default = not paused."""
    agent = AgentConfig.model_validate(
        {
            "id": "legacy-1",
            "name": "Legacy",
            "role": "analyst",
            "system_prompt": "hi",
            "provider": "openai",
            "model_name": "gpt-4o",
            "api_key": "sk-abcdefghijklmnop",
            "cron_schedule": "*/5 * * * *",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
    )
    assert agent.paused is False


def test_to_public_maps_paused() -> None:
    public = to_public(_minimal_agent(paused=True))
    assert isinstance(public, AgentPublic)
    assert public.paused is True
    assert public.cron_schedule == "0 9 * * *"
