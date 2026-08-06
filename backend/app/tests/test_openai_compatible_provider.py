"""Regression coverage for OpenAICompatibleProvider: a user reported that
bulk-classify finished suspiciously fast (implying no real AI call was
happening) while summarization worked fine and produced genuine AI output.
The code-level difference is that summarize uses complete_text (no
response_format param) while classify/analyze use complete_json (forces
response_format={"type": "json_object"}) — some endpoints/situations reject
the json_object request while a plain completion on the exact same model
succeeds. complete_json now retries once without response_format instead of
giving up immediately, and failure messages include the response body so
AIAnalysis.fallback_reason is actually diagnosable from the app."""
from __future__ import annotations

import pytest
import httpx

from app.providers.llm.base import LLMProviderError
from app.providers.llm.openai_compatible import OpenAICompatibleProvider


class _FakeResponse:
    def __init__(self, *, status_code: int, json_body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text
        self.request = httpx.Request("POST", "https://api.openai.example/v1/chat/completions")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"{self.status_code} error", request=self.request, response=self)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._json_body or {}


def _chat_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}], "usage": {}, "model": "gpt-4o-mini"}


def _install_fake_client(monkeypatch, handle_post):
    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, *, headers, json):
            return handle_post(json)

    monkeypatch.setattr("app.providers.llm.openai_compatible.httpx.AsyncClient", _FakeAsyncClient)


@pytest.mark.asyncio
async def test_complete_json_retries_without_response_format_when_json_mode_rejected(monkeypatch):
    calls: list[dict] = []

    def handle_post(payload: dict) -> _FakeResponse:
        calls.append(payload)
        if "response_format" in payload:
            return _FakeResponse(
                status_code=400,
                text='{"error": {"message": "response_format json_object is not supported by this model"}}',
            )
        return _FakeResponse(status_code=200, json_body=_chat_response('{"mail_type": "案件紹介"}'))

    _install_fake_client(monkeypatch, handle_post)
    provider = OpenAICompatibleProvider(base_url="https://api.openai.example/v1", api_key="sk-test", model="gpt-4o-mini")

    parsed, response = await provider.complete_json(system_prompt="sys", user_prompt="user")

    assert parsed == {"mail_type": "案件紹介"}
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


@pytest.mark.asyncio
async def test_complete_json_raises_with_response_body_when_both_attempts_fail(monkeypatch):
    def handle_post(payload: dict) -> _FakeResponse:
        return _FakeResponse(status_code=401, text='{"error": {"message": "Incorrect API key provided"}}')

    _install_fake_client(monkeypatch, handle_post)
    provider = OpenAICompatibleProvider(base_url="https://api.openai.example/v1", api_key="sk-bad", model="gpt-4o-mini")

    with pytest.raises(LLMProviderError) as exc_info:
        await provider.complete_json(system_prompt="sys", user_prompt="user")

    assert "Incorrect API key provided" in str(exc_info.value)


@pytest.mark.asyncio
async def test_complete_json_strips_a_markdown_code_fence_from_the_retry_response(monkeypatch):
    def handle_post(payload: dict) -> _FakeResponse:
        if "response_format" in payload:
            return _FakeResponse(status_code=400, text="response_format not supported")
        return _FakeResponse(status_code=200, json_body=_chat_response('```json\n{"mail_type": "人材紹介"}\n```'))

    _install_fake_client(monkeypatch, handle_post)
    provider = OpenAICompatibleProvider(base_url="https://api.openai.example/v1", api_key="sk-test", model="gpt-4o-mini")

    parsed, _response = await provider.complete_json(system_prompt="sys", user_prompt="user")

    assert parsed == {"mail_type": "人材紹介"}
