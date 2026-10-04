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
    # Wall-clock age after which a running ExecutionLog is treated as stuck.
    run_stuck_seconds: int = 1800
    # How often the sweeper looks for stuck runs.
    stuck_sweep_interval_seconds: int = 60
    # User and assistant messages retained verbatim in the chat prompt.
    chat_history_window: int = 24
    # Maximum size of the extractive summary for older chat turns.
    chat_summary_max_chars: int = 2000
    # Number of recent execution logs included as prior-run memory.
    run_memory_last_n: int = 3
    # Maximum text retained from each prior execution log.
    run_memory_each_max_chars: int = 600
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
