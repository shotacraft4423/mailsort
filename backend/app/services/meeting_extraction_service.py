"""会議管理: pulls Teams/Zoom/Meet links + datetime + participants out of a
message (using the AI extraction result when available, otherwise a regex
fallback so meeting links are never missed just because AI is off) and
upserts a Meeting row. Also flags reused meeting links ("Teamsリンク重複検知")
by hashing the URL.
"""
from __future__ import annotations

import hashlib
import re

from sqlalchemy.orm import Session

from app.db.models.email import Message
from app.db.models.meeting import Meeting
from app.schemas.extraction import ExtractionResult

_LINK_PATTERNS = {
    "teams": re.compile(r"https://teams\.microsoft\.com/l/meetup-join/\S+"),
    "zoom": re.compile(r"https://[\w.-]*zoom\.us/j/\S+"),
    "meet": re.compile(r"https://meet\.google\.com/\S+"),
}


def _link_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


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
            is_rescheduled=existing is not None,
            supersedes_meeting_id=existing.id if existing else None,
        )
        db.add(meeting)
        created.append(meeting)

    if created:
        db.commit()
    return created
