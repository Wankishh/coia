"""Multi-provider LLM factory."""

from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings
from app.models.agent import AgentConfig, LLMProvider


class LLMFactoryError(RuntimeError):
    """Raised when an LLM cannot be constructed."""


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def resolve_ollama_base_url(agent_base_url: Optional[str] = None) -> str:
    """Resolve OpenAI-compatible Ollama base URL (no trailing slash)."""
    settings = get_settings()
    return (agent_base_url or settings.ollama_base_url).rstrip("/")


class LLMFactory:
    """Create chat models for openai | anthropic | google | openrouter | ollama."""

    @staticmethod
    def create(agent: AgentConfig) -> BaseChatModel:
        api_key = (agent.api_key or "").strip()
        if not api_key and agent.provider != LLMProvider.ollama:
            raise LLMFactoryError(
                f"Agent '{agent.id}' has no api_key configured"
            )

        if agent.provider == LLMProvider.openai:
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=agent.model_name,
                api_key=api_key,
                temperature=0,
            )

        if agent.provider == LLMProvider.anthropic:
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=agent.model_name,
                api_key=api_key,
                temperature=0,
            )

        if agent.provider == LLMProvider.google:
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=agent.model_name,
                google_api_key=api_key,
                temperature=0,
            )

        if agent.provider == LLMProvider.openrouter:
            from langchain_openai import ChatOpenAI

            # OpenRouter is OpenAI-compatible; model ids look like
            # "openai/gpt-4o" or "anthropic/claude-3.5-sonnet".
            return ChatOpenAI(
                model=agent.model_name,
                api_key=api_key,
                base_url=OPENROUTER_BASE_URL,
                temperature=0,
                default_headers={
                    "HTTP-Referer": "https://github.com/coia-agents",
                    "X-Title": "Coia Agents",
                },
            )

        if agent.provider == LLMProvider.ollama:
            from langchain_openai import ChatOpenAI

            # Ollama OpenAI-compatible API; key is unused but required by client.
            return ChatOpenAI(
                model=agent.model_name,
                api_key=api_key or "ollama",
                base_url=resolve_ollama_base_url(agent.base_url),
                temperature=0,
            )

        raise LLMFactoryError(f"Unsupported provider: {agent.provider}")

    @staticmethod
    def create_from_params(
        provider: str,
        model_name: str,
        api_key: str,
        **kwargs: Any,
    ) -> BaseChatModel:
        agent = AgentConfig(
            name="tmp",
            role="tmp",
            system_prompt="",
            provider=LLMProvider(provider),
            model_name=model_name,
            api_key=api_key,
            base_url=kwargs.get("base_url"),
        )
        return LLMFactory.create(agent)
