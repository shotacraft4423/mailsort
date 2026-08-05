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


@pytest.mark.asyncio
async def test_local_mock_dispatches_by_task_instead_of_always_classifying():
    """Regression test: LocalMockProvider is the default provider for every
    JSON task, not just classification. It must not leak classification
    fields (mail_type/categories/...) into duplicate-check or matching-score
    callers just because they also call complete_json()."""
    provider = LocalMockProvider()

    duplicate_result, _ = await provider.complete_json(
        system_prompt="2件の案件情報が同一案件の重複か判定してください。", user_prompt="A: x\nB: y"
    )
    assert set(duplicate_result) == {"relation", "reason"}
    assert duplicate_result["relation"] == "candidate"

    matching_result, _ = await provider.complete_json(
        system_prompt="あなたはSES営業のマッチングアドバイザーです。", user_prompt="案件と人材の情報"
    )
    assert "mail_type" not in matching_result
    assert "score" not in matching_result  # caller falls back to embedding similarity when absent
    assert "rationale" in matching_result

    extraction_result, _ = await provider.complete_json(
        system_prompt="あなたはSES営業メールから構造化データを抽出するアシスタントです。", user_prompt="件名: x\n本文: y"
    )
    assert extraction_result == {}
