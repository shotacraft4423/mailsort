"""send_reply used to fire-and-forget via smtplib without ever recording the
sent email — meaning insights_service had no "Sent" data to compute reply
rate/speed from. This verifies the fix persists it correctly."""
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


def test_send_reply_persists_a_sent_message_in_the_same_thread(monkeypatch):
    with _make_client(monkeypatch) as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message, Thread

        db = SessionLocal()
        account = EmailAccount(
            display_name="me", email_address="me@example.com", protocol="imap_smtp", smtp_host="smtp.example.com"
        )
        db.add(account)
        db.flush()
        thread = Thread(account_id=account.id, subject_normalized="Java案件のご紹介")
        db.add(thread)
        db.flush()
        original = Message(
            account_id=account.id,
            thread_id=thread.id,
            folder="INBOX",
            message_uid="1",
            subject="Java案件のご紹介",
            sender_address="vendor@example.com",
        )
        db.add(original)
        db.commit()
        original_id = original.id
        thread_id = thread.id
        db.close()

        resp = client.post(
            f"/mail/{original_id}/send",
            json={"to": ["vendor@example.com"], "subject": "Re: Java案件のご紹介", "body_text": "ご連絡ありがとうございます。"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "sent"}

        db = SessionLocal()
        sent = db.query(Message).filter(Message.folder == "Sent").one()
        assert sent.thread_id == thread_id
        assert sent.sender_address == "me@example.com"
        assert sent.body_text == "ご連絡ありがとうございます。"
        db.close()


def test_send_reply_backfills_thread_id_when_original_had_none(monkeypatch):
    with _make_client(monkeypatch) as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(
            display_name="me", email_address="me@example.com", protocol="imap_smtp", smtp_host="smtp.example.com"
        )
        db.add(account)
        db.flush()
        original = Message(
            account_id=account.id,
            thread_id=None,
            folder="INBOX",
            message_uid="1",
            subject="人材のご紹介",
            sender_address="vendor@example.com",
        )
        db.add(original)
        db.commit()
        original_id = original.id
        db.close()

        resp = client.post(
            f"/mail/{original_id}/send",
            json={"to": ["vendor@example.com"], "subject": "Re: 人材のご紹介", "body_text": "承知いたしました。"},
        )
        assert resp.status_code == 200

        db = SessionLocal()
        original_after = db.query(Message).filter(Message.id == original_id).one()
        sent = db.query(Message).filter(Message.folder == "Sent").one()
        assert original_after.thread_id is not None
        assert sent.thread_id == original_after.thread_id
        db.close()
