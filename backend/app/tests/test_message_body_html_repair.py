"""Regression coverage for a real user report: messages synced before the
ImapConnector text/html fix (see services/mail/html_text.py and
test_imap_client.py's test_parse_html_only_single_part_message_...) have
raw HTML markup sitting in Message.body_text with body_html empty, since
sync_service.sync_account skips already-imported UIDs and won't re-fetch
them. GET /mail/{id} repairs this at read time instead of requiring a DB
migration or a manual re-sync."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_get_message_repairs_raw_html_left_in_body_text_by_the_old_bug():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(
            account_id=account.id,
            message_uid="1",
            subject="New sign-in to your OpenAI account",
            sender_address="noreply@tm.openai.com",
            body_text="<!DOCTYPE html><html><body><p>New sign-in detected.</p></body></html>",
            body_html="",
        )
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}")
        assert resp.status_code == 200
        body_text = resp.json()["body_text"]
        assert "<html" not in body_text.lower()
        assert "New sign-in detected." in body_text

        # Repair is display-only — the DB row itself is left as-is (no
        # surprise mutation of stored mail content on a simple GET).
        db = SessionLocal()
        from app.db.models.email import Message as MessageModel

        assert "<html" in db.query(MessageModel).filter(MessageModel.id == message_id).one().body_text.lower()
        db.close()


def test_get_message_leaves_normal_plain_text_body_untouched():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(
            account_id=account.id,
            message_uid="1",
            subject="件名",
            sender_address="a@b.com",
            body_text="こんにちは、案件のご紹介です。",
            body_html="",
        )
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}")
        assert resp.json()["body_text"] == "こんにちは、案件のご紹介です。"
