"""GUI-editable runtime settings. Values are backed by environment
variables via pydantic-settings (see core/config.py) for zero-latency reads
within a running process, and mirrored into the `app_settings` DB table
(see services/settings_service.py) so a backend restart doesn't silently
revert them to build defaults — the app's startup lifespan (main.py) loads
the persisted row back into os.environ before serving any request.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.providers.llm.registry import list_providers
from app.services.settings_service import persist_settings

router = APIRouter(prefix="/settings", tags=["settings"])

# field name -> env var name, for every value that should survive a restart.
ALL_FIELDS = {
    "ai_enabled": "MAILSORT_AI_ENABLED",
    "llm_provider": "MAILSORT_LLM_PROVIDER",
    "embedding_provider": "MAILSORT_EMBEDDING_PROVIDER",
    "openai_compatible_base_url": "MAILSORT_OPENAI_COMPATIBLE_BASE_URL",
    "openai_compatible_model": "MAILSORT_OPENAI_COMPATIBLE_MODEL",
    "anthropic_model": "MAILSORT_ANTHROPIC_MODEL",
    "anonymize_before_send": "MAILSORT_ANONYMIZE_BEFORE_SEND",
    "duplicate_similarity_threshold": "MAILSORT_DUPLICATE_SIMILARITY_THRESHOLD",
    "ui_language": "MAILSORT_UI_LANGUAGE",
    "openai_compatible_api_key": "MAILSORT_OPENAI_COMPATIBLE_API_KEY",
    "anthropic_api_key": "MAILSORT_ANTHROPIC_API_KEY",
}


def apply_env_patch(data: dict) -> None:
    """Write a {field_name: value} dict into os.environ using ALL_FIELDS,
    then drop the cached Settings instance so the next get_settings() call
    picks the new values up."""
    for field, value in data.items():
        env_key = ALL_FIELDS.get(field)
        if env_key:
            os.environ[env_key] = str(value)
    get_settings.cache_clear()


class SettingsOut(BaseModel):
    app_name: str
    ai_enabled: bool
    llm_provider: str
    embedding_provider: str
    openai_compatible_base_url: str
    openai_compatible_model: str
    anthropic_model: str
    anonymize_before_send: bool
    duplicate_similarity_threshold: float
    ui_language: str
    available_llm_providers: list[str]
    has_openai_compatible_key: bool
    has_anthropic_key: bool


class SettingsUpdate(BaseModel):
    ai_enabled: bool | None = None
    llm_provider: str | None = None
    embedding_provider: str | None = None
    openai_compatible_base_url: str | None = None
    openai_compatible_model: str | None = None
    anthropic_model: str | None = None
    anonymize_before_send: bool | None = None
    duplicate_similarity_threshold: float | None = None
    ui_language: str | None = None
    openai_compatible_api_key: str | None = None
    anthropic_api_key: str | None = None


@router.get("", response_model=SettingsOut)
def read_settings() -> SettingsOut:
    settings = get_settings()
    return SettingsOut(
        app_name=settings.app_name,
        ai_enabled=settings.ai_enabled,
        llm_provider=settings.llm_provider,
        embedding_provider=settings.embedding_provider,
        openai_compatible_base_url=settings.openai_compatible_base_url,
        openai_compatible_model=settings.openai_compatible_model,
        anthropic_model=settings.anthropic_model,
        anonymize_before_send=settings.anonymize_before_send,
        duplicate_similarity_threshold=settings.duplicate_similarity_threshold,
        ui_language=settings.ui_language,
        available_llm_providers=list_providers(),
        has_openai_compatible_key=bool(settings.openai_compatible_api_key),
        has_anthropic_key=bool(settings.anthropic_api_key),
    )


@router.put("", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsOut:
    data = payload.model_dump(exclude_none=True)
    apply_env_patch(data)
    persist_settings(db, data)
    return read_settings()
