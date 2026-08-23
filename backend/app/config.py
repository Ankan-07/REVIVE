from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH) if ENV_FILE_PATH.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""
    openai_base_url: str = ""
    default_llm_model: str = "gpt-4o-mini"
    diagnosis_llm_model: str = "gpt-4o"
    langsmith_api_key: str = ""
    langsmith_project: str = "revenue-rescue-engine"
    langsmith_tracing: bool = True
    database_url: str = "sqlite:///./revive.db"
    simulation_seed: int = 42
    # Base URL the detector uses to POST events back to this same API over real HTTP.
    internal_api_base_url: str = "http://127.0.0.1:8000"
    cors_origins: List[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


settings = Settings()
