from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Company(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Auto-aggregated counterparty. Populated/updated by
    services/company_aggregation_service.py from extraction results, not
    hand-entered (though the API allows manual edits/merges)."""

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), index=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    evaluation: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. A/B/C rank
    notes: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")

    # Rolled-up stats, recomputed periodically rather than on every message
    # write to keep ingestion fast.
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    deal_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    contract_count: Mapped[int] = mapped_column(Integer, default=0)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="company")


class Contact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "contacts"

    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    email_address: Mapped[str] = mapped_column(String(255), default="", index=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Populated by business-card OCR (services/attachment_analysis, Phase 2).
    source: Mapped[str] = mapped_column(String(32), default="email")  # email | business_card_ocr | manual

    company: Mapped[Company | None] = relationship(back_populates="contacts")
