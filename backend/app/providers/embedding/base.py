from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProviderError(RuntimeError):
    pass


class EmbeddingProvider(ABC):
    name: str = "base"
    dimensions: int = 0

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text, same order."""
