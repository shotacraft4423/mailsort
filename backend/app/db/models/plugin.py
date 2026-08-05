from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PluginConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Deliberately decoupled from every other table (no FKs into it) so
    plugins can be added/removed without touching mail/company/deal schemas.
    See services/plugin_manager.py."""

    __tablename__ = "plugin_configs"

    plugin_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)  # matches plugin.json "key"
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Encrypted via app.core.security.encrypt_secret before storage.
    config_json_encrypted: Mapped[str] = mapped_column(Text, default="")
