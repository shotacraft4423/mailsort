from __future__ import annotations

from app.core.config import Settings, get_settings
from app.providers.embedding.base import EmbeddingProvider
from app.providers.embedding.local_mock import LocalHashEmbeddingProvider
from app.providers.embedding.openai_embedding import OpenAICompatibleEmbeddingProvider


def get_embedding_provider(name: str | None = None, settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    provider_name = name or settings.embedding_provider

    if not settings.ai_enabled:
        return LocalHashEmbeddingProvider()

    if provider_name == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(
            base_url=settings.openai_compatible_base_url,
            api_key=settings.openai_compatible_api_key,
            model="text-embedding-3-small",
            timeout=settings.request_timeout_seconds,
        )
    return LocalHashEmbeddingProvider()
