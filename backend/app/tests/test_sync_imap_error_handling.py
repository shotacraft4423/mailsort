"""Regression coverage: a real IMAP connection failure (bad host/port,
wrong credentials, or the server dropping the connection —
imaplib.IMAP4.abort: socket error: EOF was the actual error seen in
production for a second configured account) propagated out of
POST /mail/accounts/{id}/sync as an unhandled 500 with a raw traceback.
The "今すぐ受信" button had nothing useful to show the user for exactly
the class of problem (account misconfiguration) that most needs a clear
message.
"""
from __future__ import annotations

import imaplib
import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_imap_connection_failure_returns_502_not_a_crash(monkeypatch):
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount

        db = SessionLocal()
        account = EmailAccount(
            display_name="a",
            email_address="a@example.com",
            protocol="imap_smtp",
            imap_host="imap.example.com",
            imap_port=993,
        )
        db.add(account)
        db.commit()
        account_id = account.id
        db.close()

        def _boom(self, folder, limit):
            raise imaplib.IMAP4.abort("socket error: EOF")

        monkeypatch.setattr("app.services.mail.imap_client.ImapConnector.fetch_new", _boom)

        resp = client.post(f"/mail/accounts/{account_id}/sync", params={"folder": "INBOX"})
        assert resp.status_code == 502
        assert "IMAP" in resp.json()["detail"]


def test_sync_without_imap_host_configured_returns_400():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.commit()
        account_id = account.id
        db.close()

        resp = client.post(f"/mail/accounts/{account_id}/sync", params={"folder": "INBOX"})
        assert resp.status_code == 400
