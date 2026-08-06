from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AppSettings(Base, TimestampMixin):
    """Single-row table persisting GUI-editable settings (api/routes/settings.py)
    across process restarts. `os.environ` (see core/config.py) is the source of
    truth *within* a running process for zero-latency reads; this table exists
    only so a restart doesn't silently revert everything (including API keys)
    back to the .env/default values, which previously made AI features look
    "broken" after every backend restart even though the user had configured
    them correctly. Whole blob is encrypted (app.core.security) since it may
    contain API keys alongside plain settings like ui_language."""

    __tablename__ = "app_settings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="default")
    config_json_encrypted: Mapped[str] = mapped_column(Text, default="")
