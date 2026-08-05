"""Offline embedding provider: deterministic feature hashing, no network.

This is NOT semantically meaningful the way a real embedding model is — it
only captures token overlap. It exists so duplicate_detection_service and
search_service have something to run against with AI disabled / no API key
configured, and so tests don't need network access. Swap for
OpenAICompatibleEmbeddingProvider (or a local Ollama/BGE server through the
same class) for real semantic similarity.
"""
from __future__ import annotations

import hashlib
import math
import re

from app.providers.embedding.base import EmbeddingProvider

_TOKEN_RE = re.compile(r"[\w぀-ヿ一-鿿]+")


class LocalHashEmbeddingProvider(EmbeddingProvider):
    name = "local_mock"
    dimensions = 256

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]
