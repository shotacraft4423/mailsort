from __future__ import annotations

import json

import pytest

from app.db.models.ai import AIAnalysis
from app.db.models.email import EmailAccount, Message
from app.db.models.rule import Rule
from app.db.models.tag import MessageTag, Tag
from app.providers.llm.base import LLMProviderError, LLMResponse
from app.services import rule_engine
from app.services.rule_engine import apply_actions, evaluate_rules


def _make_account_and_message(db_session, **kwargs) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    defaults = dict(account_id=account.id, message_uid="1", subject="お見積りの件", sender_address="a@b.com", body_text="本文")
    defaults.update(kwargs)
    message = Message(**defaults)
    db_session.add(message)
    db_session.flush()
    return message


@pytest.mark.asyncio
async def test_rule_fires_when_condition_matches(db_session):
    message = _make_account_and_message(
        db_session, subject="お見積りの件", sender_address="contact@important-client.co.jp", body_text="いつもお世話になっております。"
    )

    rule = Rule(
        name="重要顧客は常に重要",
        is_active=True,
        match_mode="all",
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "important-client"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "重要"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    fired = await evaluate_rules(db_session, message, analysis=None)
    assert len(fired) == 1
    assert fired[0].rule.name == "重要顧客は常に重要"
    assert fired[0].actions == [{"type": "tag", "params": {"tag": "重要"}}]


@pytest.mark.asyncio
async def test_inactive_rule_does_not_fire(db_session):
    message = _make_account_and_message(db_session, subject="x", sender_address="a@b.com")

    rule = Rule(
        name="disabled rule",
        is_active=False,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "b.com"}]),
        actions_json=json.dumps([{"type": "tag", "params": {}}]),
    )
    db_session.add(rule)
    db_session.commit()

    assert await evaluate_rules(db_session, message, analysis=None) == []


@pytest.mark.asyncio
async def test_apply_actions_creates_message_tag_from_tag_action(db_session):
    message = _make_account_and_message(db_session, subject="x", sender_address="a@important-client.co.jp")

    rule = Rule(
        name="重要顧客は常に重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "important-client"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "重要"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    fired = await evaluate_rules(db_session, message, analysis=None)
    apply_actions(db_session, message, fired)

    tag = db_session.query(Tag).filter(Tag.name == "重要").one()
    message_tag = db_session.query(MessageTag).filter(MessageTag.message_id == message.id).one()
    assert message_tag.tag_id == tag.id
    assert message_tag.source == "rule"
    assert message_tag.confidence == 1.0


@pytest.mark.asyncio
async def test_apply_actions_does_not_duplicate_tag_on_repeated_fire(db_session):
    message = _make_account_and_message(db_session, subject="x", sender_address="a@b.com")
    rule = Rule(
        name="r",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "b.com"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "重要"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    for _ in range(2):
        fired = await evaluate_rules(db_session, message, analysis=None)
        apply_actions(db_session, message, fired)

    count = db_session.query(MessageTag).filter(MessageTag.message_id == message.id).count()
    assert count == 1


@pytest.mark.asyncio
async def test_apply_actions_ignores_unrecognized_action_types(db_session):
    message = _make_account_and_message(db_session, subject="x", sender_address="a@b.com")
    rule = Rule(
        name="notify only",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "b.com"}]),
        actions_json=json.dumps([{"type": "notify_slack", "params": {}}]),
    )
    db_session.add(rule)
    db_session.commit()

    fired = await evaluate_rules(db_session, message, analysis=None)
    apply_actions(db_session, message, fired)  # must not raise

    assert db_session.query(MessageTag).count() == 0


@pytest.mark.asyncio
async def test_unmatched_condition_does_not_fire(db_session):
    message = _make_account_and_message(db_session, subject="x", sender_address="a@other.com")

    rule = Rule(
        name="only important-client",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "important-client"}]),
        actions_json=json.dumps([{"type": "tag", "params": {}}]),
    )
    db_session.add(rule)
    db_session.commit()

    assert await evaluate_rules(db_session, message, analysis=None) == []


def _make_analysis(db_session, message: Message) -> AIAnalysis:
    analysis = AIAnalysis(message_id=message.id, content_hash="h", provider_used="openai_compatible")
    db_session.add(analysis)
    db_session.commit()
    return analysis


class _YesProvider:
    name = "openai_compatible"
    calls = 0

    async def complete_json(self, *, system_prompt: str, user_prompt: str):
        type(self).calls += 1
        return {"matches": True}, LLMResponse(text="{}")


class _NoProvider:
    name = "openai_compatible"

    async def complete_json(self, *, system_prompt: str, user_prompt: str):
        return {"matches": False}, LLMResponse(text="{}")


class _BrokenProvider:
    name = "openai_compatible"

    async def complete_json(self, *, system_prompt: str, user_prompt: str):
        raise LLMProviderError("still failing")


@pytest.mark.asyncio
async def test_ai_prompt_condition_fires_when_provider_says_matches(db_session, monkeypatch):
    message = _make_account_and_message(db_session, subject="至急ご確認ください", body_text="大変困っております、至急対応をお願いします。")
    analysis = _make_analysis(db_session, message)

    rule = Rule(
        name="クレーム系は重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "ai_prompt", "operator": "matches", "value": "強い不満やクレームが書かれている"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "クレーム"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    monkeypatch.setattr(rule_engine, "get_llm_provider", lambda: _YesProvider())

    fired = await evaluate_rules(db_session, message, analysis)
    assert len(fired) == 1


@pytest.mark.asyncio
async def test_ai_prompt_condition_does_not_fire_when_provider_says_no_match(db_session, monkeypatch):
    message = _make_account_and_message(db_session)
    analysis = _make_analysis(db_session, message)

    rule = Rule(
        name="クレーム系は重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "ai_prompt", "operator": "matches", "value": "強い不満やクレームが書かれている"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "クレーム"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    monkeypatch.setattr(rule_engine, "get_llm_provider", lambda: _NoProvider())

    assert await evaluate_rules(db_session, message, analysis) == []


@pytest.mark.asyncio
async def test_ai_prompt_condition_result_is_cached_on_the_analysis_row(db_session, monkeypatch):
    message = _make_account_and_message(db_session)
    analysis = _make_analysis(db_session, message)

    rule = Rule(
        name="クレーム系は重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "ai_prompt", "operator": "matches", "value": "強い不満やクレームが書かれている"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "クレーム"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    _YesProvider.calls = 0
    monkeypatch.setattr(rule_engine, "get_llm_provider", lambda: _YesProvider())

    fired = await evaluate_rules(db_session, message, analysis)
    apply_actions(db_session, message, fired)
    assert _YesProvider.calls == 1

    # Re-evaluating the same message/rule (e.g. re-opening an already
    # analyzed message) must not spend a second LLM call.
    fired_again = await evaluate_rules(db_session, message, analysis)
    apply_actions(db_session, message, fired_again)
    assert _YesProvider.calls == 1
    assert len(fired_again) == 1


@pytest.mark.asyncio
async def test_ai_prompt_condition_does_not_crash_when_provider_fails(db_session, monkeypatch):
    message = _make_account_and_message(db_session)
    analysis = _make_analysis(db_session, message)

    rule = Rule(
        name="クレーム系は重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "ai_prompt", "operator": "matches", "value": "強い不満やクレームが書かれている"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "クレーム"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    monkeypatch.setattr(rule_engine, "get_llm_provider", lambda: _BrokenProvider())

    assert await evaluate_rules(db_session, message, analysis) == []


@pytest.mark.asyncio
async def test_ai_prompt_condition_never_matches_when_ai_disabled(db_session, monkeypatch):
    message = _make_account_and_message(db_session)
    analysis = _make_analysis(db_session, message)

    rule = Rule(
        name="クレーム系は重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "ai_prompt", "operator": "matches", "value": "強い不満やクレームが書かれている"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "クレーム"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    monkeypatch.setenv("MAILSORT_AI_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        assert await evaluate_rules(db_session, message, analysis) == []
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_editing_an_ai_prompt_condition_invalidates_its_cache(db_session, monkeypatch):
    """A rule's ai_prompt text changing must not reuse the old answer —
    the cache key has to be a function of the condition's own value, not
    just the rule id."""
    message = _make_account_and_message(db_session)
    analysis = _make_analysis(db_session, message)

    rule = Rule(
        name="クレーム系は重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "ai_prompt", "operator": "matches", "value": "強い不満やクレームが書かれている"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "クレーム"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    _YesProvider.calls = 0
    monkeypatch.setattr(rule_engine, "get_llm_provider", lambda: _YesProvider())
    fired = await evaluate_rules(db_session, message, analysis)
    apply_actions(db_session, message, fired)
    assert _YesProvider.calls == 1

    rule.conditions_json = json.dumps([{"field": "ai_prompt", "operator": "matches", "value": "至急対応が必要と書かれている"}])
    db_session.commit()

    fired_again = await evaluate_rules(db_session, message, analysis)
    apply_actions(db_session, message, fired_again)
    assert _YesProvider.calls == 2
