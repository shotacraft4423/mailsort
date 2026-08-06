"""Regression coverage: Meeting.starts_at was always left None regardless
of how explicit the source email's date/time was — MeetingInfo.datetime_text
was documented as "raw text as found; parsed downstream" but nothing ever
did the parsing, so the calendar view showed every meeting as
"日時未確定" even for mail that spelled out an exact date and time (e.g.
TimeRex reminder mail: "日時：2026年8月6日 (木) 11:00 - 12:00")."""
from __future__ import annotations

from datetime import datetime

from app.db.models.email import EmailAccount, Message
from app.db.models.meeting import Meeting
from app.services import meeting_extraction_service
from app.services.meeting_extraction_service import _parse_meeting_datetime


def test_parses_japanese_date_with_year_and_time_range():
    text = "日時：2026年8月6日 (木) 11:00 - 12:00（Asia/Tokyo）\nWeb会議室：https://meet.google.com/ifp-uegc-yba"
    starts_at, ends_at = _parse_meeting_datetime(text)
    assert starts_at == datetime(2026, 8, 6, 11, 0)
    assert ends_at == datetime(2026, 8, 6, 12, 0)


def test_parses_date_without_year_defaulting_to_current_year():
    starts_at, _ends_at = _parse_meeting_datetime("8月6日 11:00〜 でお願いします")
    assert starts_at is not None
    assert starts_at.month == 8
    assert starts_at.day == 6
    assert starts_at.year == datetime.now().year


def test_returns_none_when_no_date_found():
    assert _parse_meeting_datetime("お世話になっております。") == (None, None)


def test_date_only_without_time():
    starts_at, ends_at = _parse_meeting_datetime("2026年8月6日にお願いします。時間は追ってご連絡します。")
    assert starts_at == datetime(2026, 8, 6)
    assert ends_at is None


def test_extract_meetings_sets_starts_at_from_body_text(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="MONOX小岩さんとの予定は明日です",
        sender_address="reminder@timerex.net",
        body_text="日時：2026年8月6日 (木) 11:00 - 12:00（Asia/Tokyo）\nWeb会議室：https://meet.google.com/ifp-uegc-yba",
    )
    db_session.add(message)
    db_session.commit()

    created = meeting_extraction_service.extract_meetings(db_session, message, None)

    assert len(created) == 1
    meeting = db_session.query(Meeting).filter(Meeting.id == created[0].id).one()
    assert meeting.starts_at == datetime(2026, 8, 6, 11, 0)
    assert meeting.ends_at == datetime(2026, 8, 6, 12, 0)
