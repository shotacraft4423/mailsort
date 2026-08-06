"""Regression coverage: the admin UI had no way to delete a prompt template
(no DELETE route existed at all), and the "create template" form gave no
hint of what to write in the system/user prompt fields. Adds GET
/prompts/defaults (prefill source) and DELETE /prompts/{id}."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_get_defaults_returns_the_real_classification_default_prompt():
    with _make_client() as client:
        from app.services import classification_service

        resp = client.get("/prompts/defaults", params={"task": "classification"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["system_prompt"] == classification_service.DEFAULT_SYSTEM_PROMPT
        assert body["user_prompt_template"] == classification_service.DEFAULT_USER_PROMPT_TEMPLATE


def test_get_defaults_404s_for_a_task_with_no_wired_prompt_template():
    with _make_client() as client:
        resp = client.get("/prompts/defaults", params={"task": "chat"})
        assert resp.status_code == 404


def test_delete_prompt_removes_template_and_its_versions():
    with _make_client() as client:
        create_resp = client.post(
            "/prompts",
            json={
                "name": "テスト用",
                "task": "classification",
                "system_prompt": "system",
                "user_prompt_template": "user {{ subject }}",
            },
        )
        assert create_resp.status_code == 200
        template_id = create_resp.json()["id"]

        del_resp = client.delete(f"/prompts/{template_id}")
        assert del_resp.status_code == 200

        list_resp = client.get("/prompts")
        assert all(t["id"] != template_id for t in list_resp.json())

        from app.db.session import SessionLocal
        from app.db.models.ai import PromptVersion

        db = SessionLocal()
        assert db.query(PromptVersion).filter(PromptVersion.template_id == template_id).count() == 0
        db.close()


def test_delete_prompt_404s_for_unknown_id():
    with _make_client() as client:
        resp = client.delete("/prompts/does-not-exist")
        assert resp.status_code == 404
