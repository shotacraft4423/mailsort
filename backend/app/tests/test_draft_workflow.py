"""Regression coverage: previously there was no way to edit an existing
draft in place (every "save" created a new Drafts-folder row, leaving the
old one orphaned), and sending a draft left the draft row behind forever
since /send only ever created a Sent-folder copy."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client(monkeypatch) -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.api.routes import mail as mail_routes

    monkeypatch.setattr(mail_routes.smtp_client, "send_message", lambda *args, **kwargs: None)

    from app.main import app

    return TestClient(app)


def _create_account(client: TestClient) -> str:
    resp = client.post(
        "/accounts",
        json={"display_name": "me", "email_address": "me@example.com", "smtp_host": "smtp.example.com"},
    )
    return resp.json()["id"]


def test_get_message_exposes_to_and_cc_addresses(monkeypatch):
    """MessageDetailOut previously omitted to_addresses/cc_addresses
    entirely, which made resuming a draft for editing impossible — there
    was no way to know who it was addressed to."""
    with _make_client(monkeypatch) as client:
        account_id = _create_account(client)
        resp = client.post(
            "/mail/draft",
            json={"account_id": account_id, "to": ["a@b.com", "c@d.com"], "cc": ["x@y.com"], "subject": "件名", "body_text": "本文"},
        )
        draft_id = resp.json()["id"]

        resp = client.get(f"/mail/{draft_id}")
        assert resp.json()["to_addresses"] == ["a@b.com", "c@d.com"]
        assert resp.json()["cc_addresses"] == ["x@y.com"]


def test_update_draft_edits_in_place_without_creating_a_new_row(monkeypatch):
    with _make_client(monkeypatch) as client:
        account_id = _create_account(client)
        resp = client.post(
            "/mail/draft",
            json={"account_id": account_id, "to": ["a@b.com"], "subject": "下書き", "body_text": "最初の内容"},
        )
        draft_id = resp.json()["id"]

        resp = client.put(
            f"/mail/draft/{draft_id}",
            json={"account_id": account_id, "to": ["a@b.com"], "subject": "下書き（編集済み）", "body_text": "編集後の内容"},
        )
        assert resp.status_code == 200
        assert resp.json()["subject"] == "下書き（編集済み）"
        assert resp.json()["id"] == draft_id

        resp = client.get("/mail", params={"folder": "Drafts"})
        assert len(resp.json()) == 1  # not duplicated


def test_update_draft_404_for_non_draft_message(monkeypatch):
    with _make_client(monkeypatch) as client:
        account_id = _create_account(client)
        resp = client.post(
            "/mail/draft",
            json={"account_id": account_id, "to": ["a@b.com"], "subject": "x", "body_text": "y"},
        )
        draft_id = resp.json()["id"]
        client.patch(f"/mail/{draft_id}", json={"folder": "INBOX"})  # no longer a draft

        resp = client.put(
            f"/mail/draft/{draft_id}",
            json={"account_id": account_id, "to": ["a@b.com"], "subject": "z", "body_text": "w"},
        )
        assert resp.status_code == 404


def test_sending_a_draft_removes_it_and_creates_a_sent_copy(monkeypatch):
    with _make_client(monkeypatch) as client:
        account_id = _create_account(client)
        resp = client.post(
            "/mail/draft",
            json={"account_id": account_id, "to": ["buyer@example.com"], "subject": "ご提案", "body_text": "本文"},
        )
        draft_id = resp.json()["id"]

        resp = client.post(
            f"/mail/{draft_id}/send",
            json={"to": ["buyer@example.com"], "subject": "ご提案", "body_text": "本文"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "sent"}

        resp = client.get("/mail", params={"folder": "Drafts"})
        assert resp.json() == []

        resp = client.get("/mail", params={"folder": "Sent"})
        assert len(resp.json()) == 1
        assert resp.json()[0]["subject"] == "ご提案"
