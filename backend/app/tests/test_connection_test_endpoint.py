"""Coverage for POST /settings/test-connection — "APIキーの設定画面に検証
を設けたらどうかな。それでだめだったらそこにエラーを出す". Deliberately
bypasses analyze_message's content_hash cache entirely (a fresh call every
time) so it gives an unambiguous answer, unlike bulk-classify/再分類 against
an already-classified message."""
from __future__ import annotations

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.providers.llm.base import LLMProviderError, LLMResponse


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_connection_test_reports_local_mock_as_unconfigured():
    with _make_client() as client:
        # Test env defaults llm_provider to local_mock (see conftest).
        resp = client.post("/settings/test-connection")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "未設定" in body["detail"]


def test_connection_test_reports_ai_disabled(monkeypatch):
    monkeypatch.setenv("MAILSORT_AI_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    with _make_client() as client:
        resp = client.post("/settings/test-connection")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "無効化" in body["detail"]


def test_connection_test_succeeds_with_a_working_provider(monkeypatch):
    class _FakeProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return {"ok": True}, LLMResponse(text='{"ok": true}', model="gpt-4o-mini")

    import app.api.routes.settings as settings_route

    monkeypatch.setattr(settings_route, "get_llm_provider", lambda: _FakeProvider())
    with _make_client() as client:
        resp = client.post("/settings/test-connection")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "gpt-4o-mini" in body["detail"]


def test_connection_test_surfaces_the_provider_error(monkeypatch):
    class _FailingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            raise LLMProviderError("openai_compatible request failed: 401 — Incorrect API key provided")

    import app.api.routes.settings as settings_route

    monkeypatch.setattr(settings_route, "get_llm_provider", lambda: _FailingProvider())
    with _make_client() as client:
        resp = client.post("/settings/test-connection")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert "Incorrect API key provided" in body["detail"]
