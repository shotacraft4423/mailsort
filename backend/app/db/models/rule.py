from __future__ import annotations

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Rule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """No-code condition -> action rule, evaluated in addition to (and able
    to override) AI classification. e.g. "sender company is 特定企業 -> tag
    重要" or "body contains 特定キーワード -> notify Slack".

    conditions_json / actions_json hold lists of {field, operator, value}
    and {type, params} respectively — see services/rule_engine.py for the
    evaluator and the allowed vocabulary.
    """

    __tablename__ = "rules"

    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)  # lower runs first
    conditions_json: Mapped[str] = mapped_column(Text, default="[]")
    match_mode: Mapped[str] = mapped_column(String(8), default="all")  # all | any
    actions_json: Mapped[str] = mapped_column(Text, default="[]")
