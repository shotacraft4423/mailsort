"""Regression coverage: AIAnalysis.is_fallback / provider_used were tracked
in the DB (see classification_service.py's fallback-to-LocalMockProvider
path) but never exposed via GET /mail/{id}, so a user looking at a message
classified by the offline keyword fallback (e.g. suspiciously flat 55%
confidence scores across several categories) had no way to tell that's
what they were looking at rather than real AI output."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_get_message_exposes_fallback_flag_and_provider():
    with _make_client() as client:
        from app.db.models.ai import AIAnalysis
        from app.db.models.email import EmailAccount, Message
        from app.db.session import SessionLocal

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com")
        db.add(message)
        db.flush()
        db.add(
            AIAnalysis(
                message_id=message.id,
                content_hash="irrelevant",
                provider_used="local_mock",
                is_fallback=True,
                fallback_reason="openai_compatible request failed: 401 Unauthorized",
                classification_json="{}",
                extraction_json="{}",
            )
        )
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_fallback"] is True
        assert body["provider_used"] == "local_mock"
        assert body["fallback_reason"] == "openai_compatible request failed: 401 Unauthorized"


def test_get_message_without_analysis_reports_no_fallback():
    with _make_client() as client:
        from app.db.models.email import EmailAccount, Message
        from app.db.session import SessionLocal

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com")
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_fallback"] is False
        assert body["provider_used"] is None
