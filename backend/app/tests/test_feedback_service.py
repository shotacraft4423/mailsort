from __future__ import annotations

import json

import pytest

from app.db.models.ai import AIAnalysis, ClassificationFeedback
from app.db.models.email import EmailAccount, Message
from app.services import feedback_service


def _message(db_session, subject: str, body: str) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject=subject, sender_address="a@b.com", body_text=body)
    db_session.add(message)
    db_session.commit()
    return message


def test_record_correction_patches_existing_classification(db_session):
    message = _message(db_session, "案件のご紹介", "Java案件です")
    analysis = AIAnalysis(
        message_id=message.id,
        content_hash="x",
        provider_used="local_mock",
        classification_json=json.dumps({"mail_type": "案件紹介", "categories": [{"label": "案件紹介", "confidence": 0.9}]}),
    )
    db_session.add(analysis)
    db_session.commit()

    feedback_service.record_correction(db_session, message, "人材紹介", note="実際は人材紹介でした")

    db_session.refresh(analysis)
    data = json.loads(analysis.classification_json)
    assert data["mail_type"] == "人材紹介"
    assert data["categories"][0]["label"] == "人材紹介"
    assert data["categories"][0]["confidence"] == 1.0
    assert "ユーザー修正" in data["rationale"]

    stored = db_session.query(ClassificationFeedback).filter(ClassificationFeedback.message_id == message.id).one()
    assert stored.original_mail_type == "案件紹介"
    assert stored.corrected_mail_type == "人材紹介"


def test_record_correction_without_existing_analysis_still_stores_feedback(db_session):
    message = _message(db_session, "件名", "本文")
    feedback = feedback_service.record_correction(db_session, message, "案件紹介")
    assert feedback.original_mail_type is None
    assert feedback.corrected_mail_type == "案件紹介"


@pytest.mark.asyncio
async def test_get_similar_corrections_returns_empty_when_none_exist(db_session):
    message = _message(db_session, "件名", "本文")
    result = await feedback_service.get_similar_corrections(db_session, message)
    assert result == []


@pytest.mark.asyncio
async def test_get_similar_corrections_finds_matching_past_correction(db_session):
    original = _message(db_session, "Java案件のご紹介", "Java案件のご紹介です。単価70万円")
    feedback_service.record_correction(db_session, original, "人材紹介", note="実は人材紹介だった")

    new_message = _message(db_session, "Java案件のご紹介", "Java案件のご紹介です。単価65万円")
    similar = await feedback_service.get_similar_corrections(db_session, new_message)

    assert len(similar) == 1
    assert similar[0].corrected_mail_type == "人材紹介"


def test_build_few_shot_suffix_is_empty_for_no_corrections():
    assert feedback_service.build_few_shot_suffix([]) == ""


def test_build_few_shot_suffix_mentions_original_and_corrected_labels(db_session):
    message = _message(db_session, "件名", "本文")
    feedback = feedback_service.record_correction(db_session, message, "契約")
    suffix = feedback_service.build_few_shot_suffix([feedback])
    assert "契約" in suffix
