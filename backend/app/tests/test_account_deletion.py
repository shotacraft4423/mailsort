"""Regression coverage: DELETE /accounts/{id} crashed with
"NOT NULL constraint failed: messages.account_id" for any account that had
synced at least one message — SQLAlchemy's default relationship behavior
tries to null out the FK on children when the parent is deleted, but
Message.account_id is NOT NULL. EmailAccount.messages now cascades the
delete instead.
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


def test_deleting_an_account_with_messages_does_not_crash():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        db.add(Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com"))
        db.add(Message(account_id=account.id, message_uid="2", subject="件名2", sender_address="a@b.com"))
        db.commit()
        account_id = account.id
        db.close()

        resp = client.delete(f"/accounts/{account_id}")
        assert resp.status_code == 200

        db = SessionLocal()
        assert db.query(EmailAccount).filter(EmailAccount.id == account_id).one_or_none() is None
        assert db.query(Message).filter(Message.account_id == account_id).count() == 0
        db.close()
