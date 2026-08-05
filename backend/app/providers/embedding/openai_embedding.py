"""OpenAI-compatible embeddings endpoint. Covers OpenAI, Azure OpenAI,
Ollama's `/v1/embeddings` compat route, and any self-hosted service that
mirrors the OpenAI embeddings API (many BGE/E5/Jina/Nomic servers do)."""
from __future__ import annotations

import httpx

from app.providers.embedding.base import EmbeddingProvider, EmbeddingProviderError


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    name = "openai_compatible"

    def __init__(self, *, base_url: str, api_key: str, model: str, dimensions: int = 1536, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.timeout = timeout

    async def embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/embeddings", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise EmbeddingProviderError(f"{self.name} embedding request failed: {exc}") from exc
