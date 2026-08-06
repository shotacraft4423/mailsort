"""Regression coverage: meeting_extraction_service.extract_meetings() has a
regex fallback specifically so meeting links are "never missed just because
AI is off", but nothing in the app ever called it — not sync_service, not
analysis_service. The meeting calendar view and the AI panel's meeting tab
were always empty regardless of how many Teams/Zoom/Meet links a synced
email actually contained. This verifies analyze_message() now calls it.
"""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.db.models.meeting import Meeting
from app.services import analysis_service


@pytest.mark.asyncio
async def test_analyze_message_extracts_meeting_link_via_regex_fallback(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="MONOX小岩さんとの予定は明日です",
        sender_address="reminder@timerex.net",
        body_text="日時：2026年8月6日\nWeb会議室：https://meet.google.com/ifp-uegc-yba\n",
    )
    db_session.add(message)
    db_session.commit()

    await analysis_service.analyze_message(db_session, message)

    meeting = db_session.query(Meeting).filter(Meeting.source_message_id == message.id).one_or_none()
    assert meeting is not None
    assert meeting.platform == "meet"
    assert meeting.join_url == "https://meet.google.com/ifp-uegc-yba"


@pytest.mark.asyncio
async def test_analyze_message_does_not_duplicate_meetings_on_repeat_analysis(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="件名",
        sender_address="a@b.com",
        body_text="https://meet.google.com/abc-defg-hij",
    )
    db_session.add(message)
    db_session.commit()

    await analysis_service.analyze_message(db_session, message)
    await analysis_service.analyze_message(db_session, message, force=True)

    count = db_session.query(Meeting).filter(Meeting.source_message_id == message.id).count()
    assert count == 1
