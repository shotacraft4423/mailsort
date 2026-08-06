"""Regression coverage for round 2 of the real production bug: after fixing
round 1 (translated JSON key names), the very next real run hit the model
using the right key names but Japanese *values* for Literal fields —
priority="低" instead of "low", temperature="冷たい" instead of "cold",
sentiment="中立" instead of "neutral", and required booleans sent as null.
Prompt instructions are advisory; normalize_classification_payload is a
deterministic safety net applied before validation so a known synonym gets
coerced to what the schema actually requires ("そもそも日本語と英語で求め
ているvalueの対応を用意したほうが確実じゃないかな")."""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.schemas.classification import ClassificationResult
from app.services import analysis_service, classification_service
from app.services.classification_service import normalize_classification_payload


def test_normalizes_japanese_enum_values_to_the_literal_the_schema_requires():
    raw = {
        "mail_type": "案件紹介",
        "priority": "低",
        "urgency": "高",
        "sentiment": "中立",
        "temperature": "冷たい",
    }

    normalized = normalize_classification_payload(raw)

    assert normalized["priority"] == "low"
    assert normalized["urgency"] == "high"
    assert normalized["sentiment"] == "neutral"
    assert normalized["temperature"] == "cold"
    # validates cleanly now
    ClassificationResult.model_validate(normalized)


def test_coerces_null_required_booleans_to_false():
    raw = {
        "mail_type": "案件紹介",
        "meeting_related": None,
        "contract_related": None,
        "billing_related": None,
    }

    normalized = normalize_classification_payload(raw)

    assert normalized["meeting_related"] is False
    assert normalized["contract_related"] is False
    assert normalized["billing_related"] is False


def test_coerces_stray_boolean_sales_opportunity_to_none():
    raw = {"mail_type": "案件紹介", "sales_opportunity": False}

    normalized = normalize_classification_payload(raw)

    assert normalized["sales_opportunity"] is None


def test_leaves_already_valid_values_untouched():
    raw = {"mail_type": "案件紹介", "priority": "high", "sentiment": "positive"}

    normalized = normalize_classification_payload(raw)

    assert normalized["priority"] == "high"
    assert normalized["sentiment"] == "positive"


def test_unknown_synonym_is_left_alone_for_validation_to_reject_naturally():
    raw = {"mail_type": "案件紹介", "priority": "とても急ぎ"}

    normalized = normalize_classification_payload(raw)

    assert normalized["priority"] == "とても急ぎ"


def test_non_dict_input_passes_through_unchanged():
    assert normalize_classification_payload("not a dict") == "not a dict"  # type: ignore[arg-type]


def _make_message(db_session) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="案件のご紹介", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_classify_message_no_longer_falls_back_on_japanese_enum_values(db_session, monkeypatch):
    """End-to-end reproduction of the exact real-world payload shape from
    the user's server logs."""

    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {
                    "mail_type": "案件紹介",
                    "priority": "低",
                    "urgency": "低",
                    "sentiment": "中立",
                    "temperature": "冷たい",
                    "meeting_related": None,
                    "contract_related": None,
                    "billing_related": None,
                    "sales_opportunity": False,
                },
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(classification_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await classification_service.classify_message(db_session, message)

    assert outcome.analysis.is_fallback is False
    assert outcome.result.mail_type == "案件紹介"
    assert outcome.result.priority == "low"
    assert outcome.result.temperature == "cold"


@pytest.mark.asyncio
async def test_analyze_message_no_longer_falls_back_on_japanese_enum_values(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {
                    "classification": {
                        "mail_type": "人材紹介",
                        "priority": "高",
                        "sentiment": "ポジティブ",
                        "temperature": "温かい",
                        "meeting_related": None,
                    },
                    "extraction": {},
                },
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.is_fallback is False
    assert outcome.classification.mail_type == "人材紹介"
    assert outcome.classification.priority == "high"
    assert outcome.classification.temperature == "warm"
