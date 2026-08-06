"""Persists GUI-editable app settings (api/routes/settings.py) to the DB so
they survive a backend process restart. Previously these lived only in
os.environ, which meant every restart silently reverted the AI provider,
API keys, and UI language back to build defaults (local_mock, no key,
Japanese) even though the user had configured them through the Settings
screen — the app then looked like "AI features don't work at all"."""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, encrypt_secret
from app.db.models.app_settings import AppSettings

_ROW_ID = "default"


def load_persisted_settings(db: Session) -> dict:
    row = db.get(AppSettings, _ROW_ID)
    if row is None or not row.config_json_encrypted:
        return {}
    try:
        return json.loads(decrypt_secret(row.config_json_encrypted))
    except ValueError:
        # Secret key rotated or blob corrupted; fall back to build defaults
        # rather than crashing app startup.
        return {}


def persist_settings(db: Session, patch: dict) -> None:
    row = db.get(AppSettings, _ROW_ID)
    current = load_persisted_settings(db) if row is not None else {}
    current.update(patch)
    payload = encrypt_secret(json.dumps(current))
    if row is None:
        row = AppSettings(id=_ROW_ID, config_json_encrypted=payload)
        db.add(row)
    else:
        row.config_json_encrypted = payload
    db.commit()
