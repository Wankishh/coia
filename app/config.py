"""Application settings loaded from environment."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "coia_agents"
    demo_database_url: str = "postgresql+psycopg2://demo:demo@localhost:5432/demo"
    workspace_root: str = "./data/agent_workspaces"
    harness_host: str = "0.0.0.0"
    harness_port: int = 8000
    # Sync chat turn timeout (seconds); chat does not use ExecutionLog.
    chat_timeout_seconds: int = 120
    # OpenAI-compatible Ollama base (host/LAN). Used when agent.base_url is unset.
    ollama_base_url: str = "http://host.docker.internal:11434/v1"

    @property
    def workspace_path(self) -> Path:
        path = Path(self.workspace_root).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
