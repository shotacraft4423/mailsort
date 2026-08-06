"""Single HTTP client that talks to any OpenAI-Chat-Completions-compatible
endpoint. This one class covers: OpenAI, Azure OpenAI (with a base_url
override), OpenRouter, Ollama (`/v1/chat/completions` compat mode), LM
Studio, and Dify's OpenAI-compatible proxy — because they all speak the same
wire format. Anthropic's native API is different enough (message format,
no `response_format`) to warrant its own class (see anthropic.py).
"""
from __future__ import annotations

import json
import re

import httpx

from app.providers.llm.base import LLMProvider, LLMProviderError, LLMResponse

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _chat(self, *, system_prompt: str, user_prompt: str, force_json: bool) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        if force_json:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions", headers=self._headers(), json=payload
                )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            # raise_for_status()'s own message is just "400 Bad Request for
            # url ..." — the actual reason (invalid API key, model doesn't
            # support response_format=json_object, quota exhausted, ...) is
            # in the response body, which callers need to see (via
            # AIAnalysis.fallback_reason) to have any chance of diagnosing
            # "everything falls back to the offline rules" from the app
            # alone, without server console access.
            body_excerpt = exc.response.text[:300] if exc.response is not None else ""
            raise LLMProviderError(f"{self.name} request failed: {exc} — {body_excerpt}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError(f"{self.name} request failed: {exc}") from exc

        try:
            choice = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
        except (KeyError, IndexError) as exc:
            raise LLMProviderError(f"{self.name} returned an unexpected payload shape") from exc

        return LLMResponse(
            text=choice,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=data.get("model", self.model),
        )

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict, LLMResponse]:
        try:
            response = await self._chat(system_prompt=system_prompt, user_prompt=user_prompt, force_json=True)
        except LLMProviderError:
            # Some OpenAI-compatible endpoints (certain proxies/gateways,
            # older self-hosted models) reject response_format=json_object
            # outright even though a plain chat completion works fine —
            # exactly the gap between this method and complete_text, which
            # never sets it. Retry once without it and parse JSON out of
            # the free-text reply (stripping a ```json fence if the model
            # added one) instead of giving up and falling back to the
            # offline rules for every single message.
            response = await self._chat(system_prompt=system_prompt, user_prompt=user_prompt, force_json=False)

        try:
            parsed = json.loads(response.text)
        except json.JSONDecodeError:
            stripped = _CODE_FENCE_RE.sub("", response.text.strip())
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise LLMProviderError(f"{self.name} did not return valid JSON: {exc}") from exc
        return parsed, response

    async def complete_text(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        return await self._chat(system_prompt=system_prompt, user_prompt=user_prompt, force_json=False)
