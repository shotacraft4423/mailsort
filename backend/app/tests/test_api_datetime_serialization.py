"""Regression coverage for a real bug: several response models declared
datetime-backed ORM fields (Message.received_at, Company.last_contact_at,
Meeting.starts_at, AuditLogEntry.created_at) as `str`, which Pydantic v2
rejects when the value is an actual datetime instead of None — every prior
manual smoke test happened to only exercise these fields while they were
still unset. These tests populate real datetimes and go through the actual
FastAPI response serialization (not just the service layer) to catch that
class of bug.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_message_list_serializes_non_null_received_at():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        db.add(
            Message(
                account_id=account.id,
                message_uid="1",
                subject="件名",
                sender_address="a@b.com",
                received_at=datetime(2026, 8, 1, 9, 0, 0),
            )
        )
        db.commit()
        db.close()

        resp = client.get("/mail", params={"folder": "INBOX"})
        assert resp.status_code == 200
        assert resp.json()[0]["received_at"].startswith("2026-08-01")


def test_related_endpoint_serializes_non_null_company_last_contact_at():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message
        from app.db.models.company import Company

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        company = Company(name="ベンダーA", domain="vendor.example", last_contact_at=datetime(2026, 8, 1))
        db.add(company)
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="sales@vendor.example")
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}/related")
        assert resp.status_code == 200
        assert resp.json()["company"]["last_contact_at"].startswith("2026-08-01")


def test_meetings_list_serializes_non_null_starts_at():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.meeting import Meeting

        db = SessionLocal()
        db.add(Meeting(title="キックオフ", platform="teams", join_url="https://teams.example/x", starts_at=datetime(2026, 8, 5, 15, 0)))
        db.commit()
        db.close()

        resp = client.get("/meetings")
        assert resp.status_code == 200
        assert resp.json()[0]["starts_at"].startswith("2026-08-05")


def test_audit_log_endpoint_serializes_created_at():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message
        from app.db.models.ai import AuditLogEntry

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com")
        db.add(message)
        db.flush()
        db.add(
            AuditLogEntry(
                message_id=message.id,
                action="classify",
                provider_used="local_mock",
                rationale="キーワード一致のため",
                data_sent_summary="件名/本文",
                anonymized=True,
            )
        )
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}/audit-log")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["rationale"] == "キーワード一致のため"
        assert "created_at" in resp.json()[0]
