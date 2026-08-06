"""Regression coverage: GET/PUT /settings previously wrote only to
os.environ, an in-memory-per-process store. A backend restart (routine on
the Windows dev workflow: closing/reopening the uvicorn terminal) silently
reverted the LLM provider and API keys back to build defaults, which made
AI features look "broken" even though the user had configured them via the
Settings screen. main.py's lifespan now reloads a persisted DB row into
os.environ on startup; this simulates a restart by clearing the relevant
env vars and re-running that startup step directly.
"""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.main import app, _load_persisted_settings


def test_settings_survive_a_simulated_restart():
    with TestClient(app) as client:
        resp = client.put(
            "/settings",
            json={
                "llm_provider": "openai_compatible",
                "openai_compatible_api_key": "sk-test-123",
                "openai_compatible_model": "gpt-4o-mini",
                "ui_language": "en",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["llm_provider"] == "openai_compatible"
        assert body["has_openai_compatible_key"] is True
        assert body["ui_language"] == "en"

        # Simulate a process restart: os.environ is what a fresh interpreter
        # would NOT have, so clear it, but the DB (same file for the
        # duration of this `with` block) still has the persisted row.
        os.environ.pop("MAILSORT_LLM_PROVIDER", None)
        os.environ.pop("MAILSORT_OPENAI_COMPATIBLE_API_KEY", None)
        os.environ.pop("MAILSORT_UI_LANGUAGE", None)
        from app.core.config import get_settings

        get_settings.cache_clear()
        assert get_settings().llm_provider == "local_mock"  # confirms the pop actually reverted it

        _load_persisted_settings()

        resp = client.get("/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["llm_provider"] == "openai_compatible"
        assert body["has_openai_compatible_key"] is True
        assert body["ui_language"] == "en"
