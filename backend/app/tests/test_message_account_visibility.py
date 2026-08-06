"""Regression coverage: with more than one mail account configured, the
mail list/detail views had no way to tell which account a message
belonged to — every response exposed account_id (an opaque UUID) but
never the human-readable address. Message.account_email_address (a
property derived from the account relationship) is now included in
MessageOut/MessageDetailOut.
"""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_message_list_shows_which_account_each_message_belongs_to():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        work = EmailAccount(display_name="仕事用", email_address="work@example.com", protocol="imap_smtp")
        personal = EmailAccount(display_name="個人用", email_address="personal@example.com", protocol="imap_smtp")
        db.add_all([work, personal])
        db.flush()
        db.add(Message(account_id=work.id, message_uid="1", subject="件名A", sender_address="a@b.com"))
        db.add(Message(account_id=personal.id, message_uid="2", subject="件名B", sender_address="c@d.com"))
        db.commit()
        db.close()

        resp = client.get("/mail", params={"folder": "INBOX"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        addresses = {m["account_email_address"] for m in body}
        assert addresses == {"work@example.com", "personal@example.com"}


def test_message_detail_includes_account_email_address():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="仕事用", email_address="work@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com")
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}")
        assert resp.status_code == 200
        assert resp.json()["account_email_address"] == "work@example.com"
