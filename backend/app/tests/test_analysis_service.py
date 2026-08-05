from __future__ import annotations

import pytest

from app.db.models.ai import AIAnalysis
from app.db.models.email import EmailAccount, Message
from app.services import analysis_service


@pytest.mark.asyncio
async def test_analyze_message_populates_both_classification_and_extraction(db_session):
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

    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.from_cache is False
    assert outcome.classification.mail_type == "案件紹介"
    assert outcome.analysis.classification_json
    assert outcome.analysis.extraction_json


@pytest.mark.asyncio
async def test_analyze_message_is_cached_on_second_call(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="人材のご紹介",
        sender_address="sales@vendor.example",
        body_text="人材のご紹介です。",
    )
    db_session.add(message)
    db_session.commit()

    first = await analysis_service.analyze_message(db_session, message)
    second = await analysis_service.analyze_message(db_session, message)

    assert first.from_cache is False
    assert second.from_cache is True

    count = db_session.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).count()
    assert count == 1


@pytest.mark.asyncio
async def test_analyze_message_uses_one_llm_call_not_two(db_session, monkeypatch):
    """The whole point of analysis_service: one call, not classify()+extract()."""
    call_count = 0
    original = None

    from app.providers.llm.local_mock import LocalMockProvider

    original = LocalMockProvider.complete_json

    async def counting_complete_json(self, *, system_prompt, user_prompt):
        nonlocal call_count
        call_count += 1
        return await original(self, system_prompt=system_prompt, user_prompt=user_prompt)

    monkeypatch.setattr(LocalMockProvider, "complete_json", counting_complete_json)

    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()

    await analysis_service.analyze_message(db_session, message)
    assert call_count == 1
