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
from app.schemas.extraction import ExtractionResult, MeetingInfo
from app.services import meeting_extraction_service
from app.services.meeting_extraction_service import _LINK_PATTERNS, _parse_meeting_datetime


def test_teams_link_patterns_cover_the_newer_meeting_and_live_url_shapes():
    """"会議情報を拾い切れていないときがある" — the old teams pattern only
    matched the classic /l/meetup-join/ shape; a real invite using the
    newer /l/meeting/ link, or a Teams Free/personal teams.live.com link,
    matched nothing at all, so the whole meeting (not just its date) never
    showed up anywhere."""
    assert _LINK_PATTERNS["teams"].search("https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc")
    assert _LINK_PATTERNS["teams"].search("https://teams.microsoft.com/l/meeting/19%3ameeting_abc")
    assert _LINK_PATTERNS["teams"].search("https://teams.live.com/meet/1234567890")


def test_zoom_link_patterns_cover_webinar_and_personal_room_urls():
    assert _LINK_PATTERNS["zoom"].search("https://us02web.zoom.us/j/123456789")
    assert _LINK_PATTERNS["zoom"].search("https://us02web.zoom.us/w/123456789")
    assert _LINK_PATTERNS["zoom"].search("https://zoom.us/my/sales-taro")


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


def test_parses_slash_date_with_year_despite_no_trailing_kanji():
    """"会議情報を拾い切れていないときがある" — the module docstring always
    claimed "2026/8/6" was supported, but the old single regex required a
    literal 日 at the end unconditionally, so this exact slash-only
    notation (very common in casual invites and auto-generated reminders)
    never actually matched."""
    starts_at, ends_at = _parse_meeting_datetime("日時：2026/8/6 11:00-12:00")
    assert starts_at == datetime(2026, 8, 6, 11, 0)
    assert ends_at == datetime(2026, 8, 6, 12, 0)


def test_parses_slash_date_without_year_or_time():
    starts_at, ends_at = _parse_meeting_datetime("8/6(木)でお願いします。")
    assert starts_at == datetime(datetime.now().year, 8, 6)
    assert ends_at is None


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


def test_falls_back_to_body_text_when_ai_datetime_text_does_not_parse(db_session):
    """AI extraction's datetime_text ("追ってご連絡します" — the model
    correctly summarized that no date was fixed *yet*) used to be picked
    just because it was non-empty, so the regex over body_text (which does
    contain an explicit, later-confirmed date) never even ran."""
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="MONOX小岩さんとの日程調整が完了しました",
        sender_address="reminder@timerex.net",
        body_text="日時：2026年8月6日 (木) 11:00 - 12:00（Asia/Tokyo）\nWeb会議室：https://meet.google.com/ifp-uegc-yba",
    )
    db_session.add(message)
    db_session.commit()

    extraction = ExtractionResult(
        meeting=MeetingInfo(
            platform="meet",
            url="https://meet.google.com/ifp-uegc-yba",
            datetime_text="追ってご連絡します",
        )
    )

    created = meeting_extraction_service.extract_meetings(db_session, message, extraction)

    assert len(created) == 1
    meeting = db_session.query(Meeting).filter(Meeting.id == created[0].id).one()
    assert meeting.starts_at == datetime(2026, 8, 6, 11, 0)
    assert meeting.ends_at == datetime(2026, 8, 6, 12, 0)
