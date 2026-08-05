"""Central application configuration.

Everything that affects "which vendor / which model / is AI on at all" lives
here so the rest of the codebase never hardcodes a provider name. Values are
overridable via environment variables and are also mirrored into a DB-backed
Settings table (see api/routes/settings.py) so the GUI can change them at
runtime without a restart.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAILSORT_", env_file=".env", extra="ignore")

    app_name: str = "MailSort"
    data_dir: Path = Path.home() / ".mailsort"
    database_url: str = "sqlite:///./mailsort.db"

    # Master switch: when False, every AI call is short-circuited to the
    # local rule-based fallback so the app behaves as a plain mail client.
    ai_enabled: bool = True

    # Which registered provider to use by default. Individual calls may
    # override this (e.g. a specific account pinned to a local LLM for
    # privacy reasons).
    llm_provider: str = "local_mock"
    embedding_provider: str = "local_mock"

    # Generic OpenAI-compatible endpoint config. Works for OpenAI, Azure
    # OpenAI, OpenRouter, Ollama, LM Studio, and any self-hosted
    # OpenAI-compatible gateway (including Dify's OpenAI-compatible mode).
    openai_compatible_base_url: str = "https://api.openai.com/v1"
    openai_compatible_api_key: str = ""
    openai_compatible_model: str = "gpt-4o-mini"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # Privacy / masking. See core/security.py.
    anonymize_before_send: bool = True

    duplicate_similarity_threshold: float = 0.86

    request_timeout_seconds: float = 30.0

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
