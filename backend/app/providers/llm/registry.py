"""Provider factory. This is the *only* place in the codebase that should
import concrete provider classes — everything else asks for a provider by
name (or takes the configured default) and gets back an `LLMProvider`.

Adding a new vendor = add one branch here (or, for anything
OpenAI-compatible, just point `openai_compatible_base_url` at it — no code
change needed at all).
"""
from __future__ import annotations

from app.core.config import Settings, get_settings
from app.providers.llm.anthropic import AnthropicProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.local_mock import LocalMockProvider
from app.providers.llm.openai_compatible import OpenAICompatibleProvider

_KNOWN_PROVIDERS = {"openai_compatible", "anthropic", "local_mock"}


def list_providers() -> list[str]:
    return sorted(_KNOWN_PROVIDERS)


def get_llm_provider(name: str | None = None, settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    provider_name = name or settings.llm_provider

    if not settings.ai_enabled:
        return LocalMockProvider()

    if provider_name == "anthropic":
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            timeout=settings.request_timeout_seconds,
        )
    if provider_name == "openai_compatible":
        # Also covers OpenAI, Azure OpenAI, OpenRouter, Ollama, LM Studio,
        # and Dify's OpenAI-compatible mode via base_url configuration.
        return OpenAICompatibleProvider(
            base_url=settings.openai_compatible_base_url,
            api_key=settings.openai_compatible_api_key,
            model=settings.openai_compatible_model,
            timeout=settings.request_timeout_seconds,
        )
    return LocalMockProvider()
