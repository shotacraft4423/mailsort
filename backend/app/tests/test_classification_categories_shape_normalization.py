"""Round 3 of the same real-world bug class, from the user's own logs
right after round 2's enum-value fix landed: right keys, right (or
coercible) values, but categories came back as a flat list of strings —
["案件紹介"] or ["SES", "エンジニア募集"] — instead of
[{"label": "...", "confidence": ...}]. "根本的な解決案を考えて修正して" —
rather than special-case categories alone, normalize_classification_payload
now generically coerces any list[BaseModel]-typed field (categories,
reply_candidates) whether the model sends bare strings, a single dict/str
instead of a list, or dicts using a plausible alternate key name."""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.schemas.classification import ClassificationResult
from app.services import classification_service
from app.services.classification_service import normalize_classification_payload


def test_coerces_a_flat_string_list_into_category_objects():
    raw = {"mail_type": "案件紹介", "categories": ["案件紹介"]}

    normalized = normalize_classification_payload(raw)

    assert normalized["categories"] == [{"label": "案件紹介", "confidence": 0.6}]
    ClassificationResult.model_validate(normalized)


def test_coerces_multiple_bare_strings_from_the_exact_real_log_payload():
    raw = {"mail_type": "人材紹介", "categories": ["SES", "エンジニア募集"]}

    normalized = normalize_classification_payload(raw)

    assert normalized["categories"] == [
        {"label": "SES", "confidence": 0.6},
        {"label": "エンジニア募集", "confidence": 0.6},
    ]
    result = ClassificationResult.model_validate(normalized)
    assert result.top_category() in ("SES", "エンジニア募集")


def test_wraps_a_lone_string_not_sent_as_a_list():
    raw = {"mail_type": "案件紹介", "categories": "案件紹介"}

    normalized = normalize_classification_payload(raw)

    assert normalized["categories"] == [{"label": "案件紹介", "confidence": 0.6}]


def test_remaps_a_plausible_alternate_key_name():
    raw = {"mail_type": "案件紹介", "categories": [{"category": "案件紹介", "score": 0.9}]}

    normalized = normalize_classification_payload(raw)

    assert normalized["categories"] == [{"label": "案件紹介", "confidence": 0.9}]


def test_well_formed_categories_pass_through_unchanged():
    raw = {"mail_type": "案件紹介", "categories": [{"label": "案件紹介", "confidence": 0.85}]}

    normalized = normalize_classification_payload(raw)

    assert normalized["categories"] == [{"label": "案件紹介", "confidence": 0.85}]


def test_coerces_bare_strings_in_reply_candidates_too():
    raw = {"mail_type": "案件紹介", "reply_candidates": ["ご検討よろしくお願いいたします。"]}

    normalized = normalize_classification_payload(raw)

    assert normalized["reply_candidates"] == [{"tone": "ご検討よろしくお願いいたします。", "draft": ""}]
    ClassificationResult.model_validate(normalized)


def _make_message(db_session) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_classify_message_no_longer_falls_back_on_the_exact_logged_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return ({"mail_type": "人材紹介", "categories": ["SES", "エンジニア募集"]}, LLMResponse(text="{}"))

    monkeypatch.setattr(classification_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await classification_service.classify_message(db_session, message)

    assert outcome.analysis.is_fallback is False
    assert outcome.result.mail_type == "人材紹介"
    assert len(outcome.result.categories) == 2
