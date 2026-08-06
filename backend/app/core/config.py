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

    # UI display language. "ja" (default) or "en"; frontend reads/writes this
    # via GET/PUT /settings so it's a per-install choice, not per-browser.
    ui_language: str = "ja"

    # After classifying a message, move it out of INBOX into a matching
    # local folder (案件/人材/重要/要返信/Junk) — see
    # services/analysis_service.py's _route_to_category_folder. Only ever
    # touches messages currently in INBOX; Sent/Drafts/Archive/Trash and
    # anywhere the user has already filed something are left alone.
    auto_route_by_classification: bool = True

    duplicate_similarity_threshold: float = 0.86
    # How many above-threshold candidates get an LLM verification call per
    # duplicate-check run. Embedding similarity is cheap (or free, with the
    # offline hash embedder); the LLM call is not — this bounds the worst
    # case (many similar-looking deals/candidates) to a fixed cost instead
    # of one call per match.
    duplicate_llm_verification_top_n: int = 5

    # Token-budget controls. Both cut input tokens on every AI call without
    # changing what gets *stored* (the full body/attachment text is still
    # saved to the DB; only what's sent to the LLM is capped). Defaults are
    # sized for a low-cost model (gpt-4o-mini) on a metered/trial plan.
    max_body_chars_for_ai: int = 4000
    max_attachment_excerpt_chars: int = 1500

    request_timeout_seconds: float = 30.0

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
