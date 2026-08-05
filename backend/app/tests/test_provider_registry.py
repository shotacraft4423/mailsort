from __future__ import annotations

import pytest

from app.providers.llm.local_mock import LocalMockProvider
from app.providers.llm.openai_compatible import OpenAICompatibleProvider
from app.providers.llm.registry import get_llm_provider


def test_ai_disabled_always_returns_local_mock(monkeypatch):
    monkeypatch.setenv("MAILSORT_AI_ENABLED", "false")
    monkeypatch.setenv("MAILSORT_LLM_PROVIDER", "openai_compatible")
    from app.core.config import get_settings

    get_settings.cache_clear()
    provider = get_llm_provider()
    assert isinstance(provider, LocalMockProvider)


def test_configured_provider_is_used_when_ai_enabled(monkeypatch):
    monkeypatch.setenv("MAILSORT_AI_ENABLED", "true")
    monkeypatch.setenv("MAILSORT_LLM_PROVIDER", "openai_compatible")
    from app.core.config import get_settings

    get_settings.cache_clear()
    provider = get_llm_provider()
    assert isinstance(provider, OpenAICompatibleProvider)


def test_unknown_provider_name_falls_back_to_local_mock():
    provider = get_llm_provider(name="totally_unknown_vendor")
    assert isinstance(provider, LocalMockProvider)


@pytest.mark.asyncio
async def test_local_mock_never_raises_and_returns_dict():
    provider = LocalMockProvider()
    result, response = await provider.complete_json(system_prompt="sys", user_prompt="案件のご紹介です。ご返信お待ちしております。")
    assert isinstance(result, dict)
    assert result["mail_type"] == "案件紹介"
    assert result["reply_required"] is True
    assert response.model == "local_mock"
