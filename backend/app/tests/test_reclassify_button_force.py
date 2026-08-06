"""Regression coverage: the message detail's "再分類" (re-classify) button
called POST /ai/messages/{id}/analyze without force=true, so for any
message whose content hadn't changed (the overwhelming common case — the
user is re-classifying because a *result* was wrong, not because the mail
itself changed) it just silently returned the same cached AIAnalysis row
every time. This made the button a no-op exactly when someone needed it
most: after a classification-logic bugfix, or after fixing a broken AI
provider connection, clicking "再分類" on an already-classified message
kept showing the stale/fallback result forever."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_analyze_without_force_returns_cached_result_for_unchanged_content():
    with _make_client() as client:
        from app.db.models.email import EmailAccount, Message
        from app.db.session import SessionLocal

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(
            account_id=account.id, message_uid="1", subject="案件のご紹介", sender_address="a@b.com", body_text="案件のご紹介です。"
        )
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        first = client.post(f"/ai/messages/{message_id}/analyze")
        assert first.status_code == 200
        assert first.json()["from_cache"] is False

        second = client.post(f"/ai/messages/{message_id}/analyze")
        assert second.status_code == 200
        assert second.json()["from_cache"] is True


def test_analyze_with_force_reruns_even_when_content_is_unchanged():
    with _make_client() as client:
        from app.db.models.email import EmailAccount, Message
        from app.db.session import SessionLocal

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(
            account_id=account.id, message_uid="1", subject="案件のご紹介", sender_address="a@b.com", body_text="案件のご紹介です。"
        )
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        first = client.post(f"/ai/messages/{message_id}/analyze")
        assert first.json()["from_cache"] is False

        # This is what the "再分類" button must send — without it, clicking
        # re-classify on unchanged content is indistinguishable from doing
        # nothing at all.
        forced = client.post(f"/ai/messages/{message_id}/analyze", params={"force": "true"})
        assert forced.status_code == 200
        assert forced.json()["from_cache"] is False
