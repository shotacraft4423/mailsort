"""Regression coverage: opening a message never marked it read (is_read
was only ever set on the Sent-copy path in send_reply), and there was no
way at all to flag a message or move it between folders (archive/trash)."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_getting_a_message_marks_it_read():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", is_read=False)
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}")
        assert resp.status_code == 200
        assert resp.json()["is_read"] is True

        db = SessionLocal()
        assert db.query(Message).filter(Message.id == message_id).one().is_read is True
        db.close()


def test_patch_message_can_flag_and_mark_unread():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", is_read=True)
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.patch(f"/mail/{message_id}", json={"is_flagged": True, "is_read": False})
        assert resp.status_code == 200
        assert resp.json()["is_flagged"] is True
        assert resp.json()["is_read"] is False


def test_patch_message_can_move_folder_for_archive_and_trash():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", folder="INBOX")
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.patch(f"/mail/{message_id}", json={"folder": "Trash"})
        assert resp.status_code == 200
        assert resp.json()["folder"] == "Trash"

        # Moved messages disappear from their old folder's listing.
        resp = client.get("/mail", params={"folder": "INBOX"})
        assert all(m["id"] != message_id for m in resp.json())

        resp = client.get("/mail", params={"folder": "Trash"})
        assert any(m["id"] == message_id for m in resp.json())


def test_patch_message_404_for_unknown_id():
    with _make_client() as client:
        resp = client.patch("/mail/does-not-exist", json={"is_read": True})
        assert resp.status_code == 404
