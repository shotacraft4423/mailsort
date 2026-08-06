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
async def test_message_misrouted_to_the_wrong_auto_folder_gets_corrected(db_session):
    """A real user report: a 人材紹介 message ended up filed under 案件 (and
    人材 stayed empty) and running "AI分類を実行"/bulk-classify again did
    not fix it — because the message was no longer in INBOX, the old guard
    treated it as "already filed on purpose" and left it exactly where it
    (wrongly) already was. Re-routing must be able to correct its own past
    decisions, not just file brand-new INBOX mail."""
    message = _make_message(db_session, subject="人材のご紹介", body_text="人材のご紹介です。", folder="案件")

    await analysis_service.analyze_message(db_session, message, force=True)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "人材"


@pytest.mark.asyncio
async def test_message_manually_filed_by_a_rule_into_a_custom_folder_is_left_alone(db_session):
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。", folder="最重要顧客")

    await analysis_service.analyze_message(db_session, message, force=True)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "最重要顧客"


@pytest.mark.asyncio
async def test_routing_disabled_via_settings_leaves_message_in_inbox(db_session, monkeypatch):
    monkeypatch.setenv("MAILSORT_AUTO_ROUTE_BY_CLASSIFICATION", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。")

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "INBOX"


@pytest.mark.asyncio
async def test_a_cached_reclassify_still_routes_a_message_that_was_never_routed(db_session, monkeypatch):
    """Reproduces "全部分類したのにフォルダ分けされない": a message analyzed
    while routing was off (or before routing existed at all) has a cached
    AIAnalysis row. Re-running "AI分類を実行"/bulk-classify without
    force=True hits that cache — routing must still apply there, not only
    on a fresh (uncached) analysis."""
    from app.core.config import get_settings

    monkeypatch.setenv("MAILSORT_AUTO_ROUTE_BY_CLASSIFICATION", "false")
    get_settings.cache_clear()
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。")
    await analysis_service.analyze_message(db_session, message)
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "INBOX"

    monkeypatch.setenv("MAILSORT_AUTO_ROUTE_BY_CLASSIFICATION", "true")
    get_settings.cache_clear()
    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.from_cache is True
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "案件"
