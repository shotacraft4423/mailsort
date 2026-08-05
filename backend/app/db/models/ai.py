from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIAnalysis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """1:1 AI result attached to a Message. `content_hash` is
    sha256(subject+body+attachment names) so re-ingesting an unchanged
    message (e.g. re-sync after reconnect) is a cache hit instead of a new
    LLM call — see services/classification_service.py."""

    __tablename__ = "ai_analyses"

    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id"), unique=True, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    provider_used: Mapped[str] = mapped_column(String(64))
    prompt_template_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("prompt_templates.id"), nullable=True)
    model_used: Mapped[str] = mapped_column(String(128), default="")

    # Raw JSON payloads, validated against app.schemas.classification /
    # app.schemas.extraction at write time but stored as text so unknown /
    # future fields are never lost.
    classification_json: Mapped[str] = mapped_column(Text, default="{}")
    extraction_json: Mapped[str] = mapped_column(Text, default="{}")
    summary_3line: Mapped[str] = mapped_column(Text, default="")
    summary_10line: Mapped[str] = mapped_column(Text, default="")
    summary_detailed: Mapped[str] = mapped_column(Text, default="")

    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)  # produced by offline rule-based classifier
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PromptTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """GUI-editable prompt, versioned. `task` selects which pipeline stage it
    drives (classification | extraction | summary | reply_suggestion |
    duplicate_check | chat)."""

    __tablename__ = "prompt_templates"

    name: Mapped[str] = mapped_column(String(255))
    task: Mapped[str] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    active_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    versions: Mapped[list["PromptVersion"]] = relationship(back_populates="template", cascade="all, delete-orphan")


class PromptVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "prompt_versions"

    template_id: Mapped[str] = mapped_column(String(36), ForeignKey("prompt_templates.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt_template: Mapped[str] = mapped_column(Text)  # Jinja-style {{ variables }}
    notes: Mapped[str] = mapped_column(Text, default="")

    template: Mapped[PromptTemplate] = relationship(back_populates="versions")


class TokenUsageLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "token_usage_logs"

    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    task: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.id"), nullable=True)


class AuditLogEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """"AIがなぜこのメールを案件紹介と判断したか" — a human-readable rationale
    plus the exact data sent, so classification decisions can be audited."""

    __tablename__ = "audit_log_entries"

    message_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("messages.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64))  # classify | extract | duplicate_check | reply_suggest | rule_fire
    provider_used: Mapped[str] = mapped_column(String(64), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    data_sent_summary: Mapped[str] = mapped_column(Text, default="")  # what fields were sent, masked or not
    anonymized: Mapped[bool] = mapped_column(Boolean, default=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # reserved for multi-user (Phase 3)


class AnalysisQueueItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """DB-backed background job queue (see services/queue.py). Swappable for
    Celery+Redis at commercial scale without changing the producer API."""

    __tablename__ = "analysis_queue"

    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id"), index=True)
    task: Mapped[str] = mapped_column(String(64))  # classify | extract | summarize | duplicate_check | meeting_extract
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
