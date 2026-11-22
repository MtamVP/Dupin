"""Application configuration supporting local-first and API-backed LLM modes."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(env_prefix="STALKER_", env_file=".env", extra="ignore")

    app_name: str = "Stalker++ OSINT Workbench"
    db_path: Path = Path("data/stalker_pp.db")

    # LLM Provider Configuration: local Ollama or external API
    llm_provider: Literal["ollama", "openai", "gemini", "anthropic", "none"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # Investigation safety & resource bounds
    max_search_depth: int = 4
    max_queries_per_run: int = 30
    http_timeout_seconds: float = 15.0


settings = Settings()
