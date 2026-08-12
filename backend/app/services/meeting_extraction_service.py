"""会議管理: pulls Teams/Zoom/Meet links + datetime + participants out of a
message (using the AI extraction result when available, otherwise a regex
fallback so meeting links are never missed just because AI is off) and
upserts a Meeting row. Also flags reused meeting links ("Teamsリンク重複検知")
by hashing the URL.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.email import Message
from app.db.models.meeting import Meeting
from app.schemas.extraction import ExtractionResult

_LINK_PATTERNS = {
    # "会議情報を拾い切れていないときがある" — these only ever matched the
    # single most common URL shape for each platform (old-style Teams
    # meetup-join links, zoom.us/j/ join links only). Real invites also use
    # /l/meeting/ (Teams' newer scheduled-meeting links), teams.live.com
    # (Teams Free/personal), and Zoom's /w/ (webinar) and /my/ (personal
    # room) paths — any of those fell through to no match at all, and since
    # extract_meetings() only creates a Meeting row when it finds a URL,
    # the whole meeting silently never showed up anywhere, not just its
    # date/time.
    "teams": re.compile(r"https://teams\.microsoft\.com/l/(?:meetup-join|meeting)/\S+|https://teams\.live\.com/meet/\S+"),
    "zoom": re.compile(r"https://[\w.-]*zoom\.us/(?:j|w|my)/\S+"),
    "meet": re.compile(r"https://meet\.google\.com/\S+"),
}

# "2026年8月6日" / "2026/8/6" / "8月6日" / "8/6" / "8/6(木)" (year optional —
# defaults to this year, since reminder mail like TimeRex's rarely spells
# it out for same-year meetings). This used to be a single pattern
# requiring a literal "日" at the end unconditionally
# ((?:(\d{4})[年/])?(\d{1,2})月?/?(\d{1,2})日) — despite this comment always
# claiming "2026/8/6" was supported, that slash-only notation (extremely
# common in casual invites and auto-generated meeting reminders) has no
# trailing 日 at all and never actually matched, so those meetings' dates
# silently stayed 日時未確定 no matter how explicit the email was. Two
# separate alternatives now: the kanji form still requires 月/日, the
# slash form doesn't require either.
_DATE_RE = re.compile(
    r"(?:(?P<kanji_year>\d{4})年)?(?P<kanji_month>\d{1,2})月(?P<kanji_day>\d{1,2})日"
    r"|(?:(?P<slash_year>\d{4})/)?(?P<slash_month>\d{1,2})/(?P<slash_day>\d{1,2})"
)
# "11:00 - 12:00" / "11:00〜12:00" / "11:00" alone.
_TIME_RANGE_RE = re.compile(r"(\d{1,2}):(\d{2})(?:\s*[〜~\-−]\s*(\d{1,2}):(\d{2}))?")


def _link_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def _parse_meeting_datetime(text: str) -> tuple[datetime | None, datetime | None]:
    """MeetingInfo.datetime_text is documented as "raw text as found; parsed
    downstream" but nothing ever did the parsing — Meeting.starts_at was
    always left None regardless of how explicit the source email was (e.g.
    "日時：2026年8月6日 (木) 11:00 - 12:00"), so the calendar view showed
    every meeting as "日時未確定". This is a best-effort parser for common
    Japanese date/time notations, not a full natural-language parser."""
    date_match = _DATE_RE.search(text)
    if not date_match:
        return None, None
    groups = date_match.groupdict()
    if groups["kanji_month"] is not None:
        year_str, month_str, day_str = groups["kanji_year"], groups["kanji_month"], groups["kanji_day"]
    else:
        year_str, month_str, day_str = groups["slash_year"], groups["slash_month"], groups["slash_day"]
    year = int(year_str) if year_str else datetime.now().year
    month, day = int(month_str), int(day_str)

    time_match = _TIME_RANGE_RE.search(text, date_match.end()) or _TIME_RANGE_RE.search(text)
    if not time_match:
        try:
            return datetime(year, month, day), None
        except ValueError:
            return None, None

    start_h, start_m, end_h, end_m = time_match.groups()
    try:
        starts_at = datetime(year, month, day, int(start_h), int(start_m))
    except ValueError:
        return None, None

    ends_at = None
    if end_h and end_m:
        try:
            ends_at = datetime(year, month, day, int(end_h), int(end_m))
        except ValueError:
            ends_at = None
    return starts_at, ends_at


def extract_meetings(db: Session, message: Message, extraction: ExtractionResult | None) -> list[Meeting]:
    urls: list[tuple[str, str]] = []  # (platform, url)

    if extraction and extraction.meeting and extraction.meeting.url:
        urls.append((extraction.meeting.platform or "unknown", extraction.meeting.url))
    if extraction:
        for platform in ("teams", "meet", "zoom"):
            for url in getattr(extraction.tool_links, platform, []):
                urls.append((platform, url))

    if not urls:
        for platform, pattern in _LINK_PATTERNS.items():
            for match in pattern.finditer(message.body_text or ""):
                urls.append((platform, match.group()))

    # AI-extracted datetime_text is tried first (the model saw the whole
    # email, including phrasing a regex won't) but it's free-text the model
    # wrote, not guaranteed to contain something _parse_meeting_datetime can
    # read (e.g. "追ってご連絡します") — picking it just because it's
    # non-empty used to mean body_text's regex fallback never even ran, so
    # a message whose body plainly said "日時：2026年8月6日 11:00-12:00"
    # still showed 日時未確定 if the model's own summary of that date didn't
    # parse. Try each candidate in priority order and keep the first one
    # that actually yields a date.
    starts_at, ends_at = None, None
    for candidate in (
        extraction.meeting.datetime_text if extraction and extraction.meeting else None,
        message.body_text,
    ):
        if not candidate:
            continue
        starts_at, ends_at = _parse_meeting_datetime(candidate)
        if starts_at is not None:
            break

    created: list[Meeting] = []
    seen = set()
    for platform, url in urls:
        if url in seen:
            continue
        seen.add(url)
        link_hash = _link_hash(url)

        existing = (
            db.query(Meeting)
            .filter(Meeting.platform_link_hash == link_hash, Meeting.source_message_id != message.id)
            .order_by(Meeting.created_at.desc())
            .first()
        )

        meeting = Meeting(
            source_message_id=message.id,
            title=message.subject,
            platform=platform,
            join_url=url,
            platform_link_hash=link_hash,
            starts_at=starts_at,
            ends_at=ends_at,
            is_rescheduled=existing is not None,
            supersedes_meeting_id=existing.id if existing else None,
        )
        db.add(meeting)
        created.append(meeting)

    if created:
        db.commit()
    return created
