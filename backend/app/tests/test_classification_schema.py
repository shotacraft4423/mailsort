from __future__ import annotations

import json

import pytest

from app.db.models.email import EmailAccount, Message
from app.schemas.classification import ClassificationResult
from app.services import classification_service


def test_unknown_category_and_extra_fields_survive_round_trip():
    """柔軟設計要件: an LLM-provided category/field outside the seed taxonomy
    must not be dropped by the schema."""
    raw = {
        "mail_type": "新種別カテゴリ",  # not in DEFAULT_CATEGORIES
        "categories": [{"label": "新種別カテゴリ", "confidence": 0.9, "extra_note": "future field"}],
        "some_future_field": {"nested": True},
    }
    result = ClassificationResult.model_validate(raw)
    dumped = result.model_dump()
    assert dumped["mail_type"] == "新種別カテゴリ"
    assert dumped["some_future_field"] == {"nested": True}
    assert dumped["categories"][0]["extra_note"] == "future field"


def test_top_category_picks_highest_confidence():
    result = ClassificationResult(
        mail_type="案件紹介",
        categories=[
            {"label": "案件紹介", "confidence": 0.97},
            {"label": "要返信", "confidence": 0.88},
            {"label": "重要", "confidence": 0.75},
        ],
    )
    assert result.top_category() == "案件紹介"


@pytest.mark.asyncio
async def test_classify_message_caches_by_content_hash(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="Java案件のご紹介",
        sender_address="sales@vendor.example",
        body_text="Java案件のご紹介です。ご返信お待ちしております。",
    )
    db_session.add(message)
    db_session.commit()

    first = await classification_service.classify_message(db_session, message)
    assert first.from_cache is False
    assert first.analysis.is_fallback is False  # local_mock is the configured provider, not a fallback path
    assert first.result.mail_type == "案件紹介"

    second = await classification_service.classify_message(db_session, message)
    assert second.from_cache is True
    assert json.loads(second.analysis.classification_json)["mail_type"] == "案件紹介"
