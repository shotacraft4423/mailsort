from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_list_folders_returns_parsed_names(monkeypatch):
    from app.api.routes import accounts as accounts_routes

    monkeypatch.setattr(
        accounts_routes.ImapConnector, "list_folders", lambda self: ["INBOX", "Sent", "[Gmail]/Sent Mail"]
    )

    with _make_client() as client:
        resp = client.post(
            "/accounts",
            json={"display_name": "a", "email_address": "a@example.com", "imap_host": "imap.example.com"},
        )
        account_id = resp.json()["id"]

        resp = client.get(f"/accounts/{account_id}/folders")
        assert resp.status_code == 200
        assert resp.json() == ["INBOX", "Sent", "[Gmail]/Sent Mail"]


def test_list_folders_404_for_unknown_account():
    with _make_client() as client:
        resp = client.get("/accounts/does-not-exist/folders")
        assert resp.status_code == 404


def test_list_folders_400_when_no_imap_host_configured():
    with _make_client() as client:
        resp = client.post("/accounts", json={"display_name": "a", "email_address": "a@example.com"})
        account_id = resp.json()["id"]

        resp = client.get(f"/accounts/{account_id}/folders")
        assert resp.status_code == 400


def test_list_folders_502_on_connection_failure(monkeypatch):
    import imaplib

    from app.api.routes import accounts as accounts_routes

    def _raise(self):
        raise imaplib.IMAP4.error("connection refused")

    monkeypatch.setattr(accounts_routes.ImapConnector, "list_folders", _raise)

    with _make_client() as client:
        resp = client.post(
            "/accounts",
            json={"display_name": "a", "email_address": "a@example.com", "imap_host": "imap.example.com"},
        )
        account_id = resp.json()["id"]

        resp = client.get(f"/accounts/{account_id}/folders")
        assert resp.status_code == 502
