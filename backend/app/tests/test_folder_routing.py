"""Regression coverage: classification produced tags/badges the user had
to go looking for, but nothing ever moved a message anywhere based on the
result — every classified message just sat in INBOX regardless of
category. analyze_message now routes INBOX messages into a matching local
folder (案件/人材/重要/要返信/Junk) once classified.
"""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.services import analysis_service


def _make_message(db_session, *, subject: str, body_text: str, folder: str = "INBOX") -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject=subject, sender_address="a@b.com", body_text=body_text, folder=folder)
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_deal_introduction_email_is_routed_to_deal_folder(db_session):
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。")

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "案件"


@pytest.mark.asyncio
async def test_candidate_introduction_email_is_routed_to_candidate_folder(db_session):
    message = _make_message(db_session, subject="人材のご紹介", body_text="人材のご紹介です。")

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "人材"


@pytest.mark.asyncio
async def test_message_not_in_inbox_is_never_moved(db_session):
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。", folder="Archive")

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "Archive"


@pytest.mark.asyncio
async def test_routing_disabled_via_settings_leaves_message_in_inbox(db_session, monkeypatch):
    monkeypatch.setenv("MAILSORT_AUTO_ROUTE_BY_CLASSIFICATION", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。")

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "INBOX"
