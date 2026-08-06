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
    "teams": re.compile(r"https://teams\.microsoft\.com/l/meetup-join/\S+"),
    "zoom": re.compile(r"https://[\w.-]*zoom\.us/j/\S+"),
    "meet": re.compile(r"https://meet\.google\.com/\S+"),
}

# "2026年8月6日" / "2026/8/6" / "8月6日" (year optional — defaults to this
# year, since reminder mail like TimeRex's rarely spells it out for
# same-year meetings).
_DATE_RE = re.compile(r"(?:(\d{4})[年/])?(\d{1,2})月?/?(\d{1,2})日")
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
    year_str, month_str, day_str = date_match.groups()
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

    # AI-extracted datetime_text takes priority (the model saw the whole
    # email, including phrasing a regex won't); body_text is the fallback
    # so a date still gets parsed when AI is off or didn't fill this in.
    datetime_source = (extraction.meeting.datetime_text if extraction and extraction.meeting else None) or message.body_text or ""
    starts_at, ends_at = _parse_meeting_datetime(datetime_source)

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
