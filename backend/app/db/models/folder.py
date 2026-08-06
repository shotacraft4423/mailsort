from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CustomFolder(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """User-created folders beyond the built-in 案件/人材/重要/要返信/Junk
    set (those five are wired into analysis_service's classification
    heuristic and always exist; this table is purely so a folder the user
    wants to route mail into via a rule shows up in the sidebar even
    before any mail has actually landed there, and can be removed again).
    """

    __tablename__ = "custom_folders"

    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
