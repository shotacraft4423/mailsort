from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Deal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """案件 (project/engagement offer). One row is created per distinct
    project extracted from a 案件紹介 message; duplicate_detection_service
    links likely-duplicate Deals via `duplicate_of_id` rather than merging
    them outright, so provenance (which company sent which price) is kept."""

    __tablename__ = "deals"

    source_message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.id"), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True, index=True)

    title: Mapped[str] = mapped_column(String(500))
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_price_min: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 単価(万円/月)
    unit_price_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headcount: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 募集人数
    business_flow: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 商流 (元請/1次/2次...)
    work_style: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 常駐/リモート/ハイブリッド
    foreign_nationality_ok: Mapped[bool | None] = mapped_column(nullable=True)
    interview_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    reply_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open | closed | filled
    notes: Mapped[str] = mapped_column(Text, default="")

    duplicate_of_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("deals.id"), nullable=True)
    duplicate_relation: Mapped[str | None] = mapped_column(String(32), nullable=True)  # exact | candidate | different_flow


class Candidate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """人材 (engineer/candidate) extracted from 人材紹介 messages, or held in
    the in-house bench for matching against inbound Deals."""

    __tablename__ = "candidates"

    source_message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.id"), nullable=True)
    company_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("companies.id"), nullable=True, index=True)

    display_name: Mapped[str] = mapped_column(String(255))  # often anonymized (e.g. "Aさん")
    skills_json: Mapped[str] = mapped_column(Text, default="[]")
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nationality: Mapped[str | None] = mapped_column(String(64), nullable=True)
    available_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    unit_price_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_preference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_flow: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open | assigned | closed
    notes: Mapped[str] = mapped_column(Text, default="")

    duplicate_of_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("candidates.id"), nullable=True)
    duplicate_relation: Mapped[str | None] = mapped_column(String(32), nullable=True)


class MatchScore(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """案件・人材マッチングスコア (Phase 2 feature, modeled now so the schema
    doesn't need to change later): precomputed compatibility between a Deal
    and a Candidate."""

    __tablename__ = "match_scores"

    deal_id: Mapped[str] = mapped_column(String(36), ForeignKey("deals.id"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), ForeignKey("candidates.id"), index=True)
    score: Mapped[float] = mapped_column(default=0.0)  # 0-1 estimated success likelihood
    rationale: Mapped[str] = mapped_column(Text, default="")
