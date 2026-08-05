from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Tag(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_system: Mapped[bool] = mapped_column(default=False)  # seeded taxonomy vs user-created


class MessageTag(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Multi-tag assignment with per-tag AI confidence, e.g. 案件紹介 0.97."""

    __tablename__ = "message_tags"

    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id"), index=True)
    tag_id: Mapped[str] = mapped_column(String(36), ForeignKey("tags.id"), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source: Mapped[str] = mapped_column(String(16), default="ai")  # ai | user | rule
