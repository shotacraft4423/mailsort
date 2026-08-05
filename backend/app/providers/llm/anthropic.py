"""Native Anthropic Messages API provider. Kept dependency-free (raw httpx)
so the backend doesn't require the `anthropic` SDK just to boot."""
from __future__ import annotations

import json
import re

import httpx

from app.providers.llm.base import LLMProvider, LLMProviderError, LLMResponse

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, *, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def _messages(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMProviderError(f"{self.name} request failed: {exc}") from exc

        try:
            text = "".join(block.get("text", "") for block in data["content"])
            usage = data.get("usage", {})
        except (KeyError, TypeError) as exc:
            raise LLMProviderError(f"{self.name} returned an unexpected payload shape") from exc

        return LLMResponse(
            text=text,
            prompt_tokens=usage.get("input_tokens", 0),
            completion_tokens=usage.get("output_tokens", 0),
            model=data.get("model", self.model),
        )

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict, LLMResponse]:
        json_instruction = (
            system_prompt
            + "\n\nRespond with a single JSON object only. No prose, no markdown code fences."
        )
        response = await self._messages(system_prompt=json_instruction, user_prompt=user_prompt)
        match = _JSON_BLOCK_RE.search(response.text)
        if not match:
            raise LLMProviderError(f"{self.name} did not return a JSON object")
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"{self.name} returned malformed JSON: {exc}") from exc
        return parsed, response

    async def complete_text(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        return await self._messages(system_prompt=system_prompt, user_prompt=user_prompt)
