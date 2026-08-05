from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Meeting(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Extracted from message bodies by services/meeting_extraction_service.py.
    platform_link_hash is used for Teams/Zoom/Meet link-reuse detection
    ("Teamsリンク重複検知")."""

    __tablename__ = "meetings"

    source_message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.id"), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True)

    title: Mapped[str] = mapped_column(String(500), default="")
    platform: Mapped[str] = mapped_column(String(32), default="unknown")  # teams | zoom | meet | other
    join_url: Mapped[str] = mapped_column(Text, default="")
    platform_link_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    participants_json: Mapped[str] = mapped_column(Text, default="[]")
    is_rescheduled: Mapped[bool] = mapped_column(Boolean, default=False)
    supersedes_meeting_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("meetings.id"), nullable=True)
