"""LLM provider interface.

Every AI-provider integration (OpenAI, Claude, Gemini, OpenRouter, Ollama,
LM Studio, Azure OpenAI, any OpenAI-compatible endpoint, Dify) implements
this same interface. Callers (services/classification_service.py etc.)
never import a concrete provider directly — they go through
providers/llm/registry.py — so switching vendors is a config change, not a
code change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class LLMProviderError(RuntimeError):
    """Raised on network failure, auth failure, rate limit, or malformed
    response. Callers (classification_service) catch this and fall back to
    the offline rule-based classifier rather than surfacing a hard error —
    this is what satisfies "API障害時でも通常のメーラーとして使用可能"."""


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict, LLMResponse]:
        """Ask the model for a JSON object and return it parsed, alongside
        raw usage metadata. Implementations should instruct the model to
        emit JSON only (e.g. response_format / prompt instruction) and must
        raise LLMProviderError if parsing fails after retries."""

    @abstractmethod
    async def complete_text(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Free-form text completion, used for reply drafting and chat."""
