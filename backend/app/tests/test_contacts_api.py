"""Coverage for the new /contacts endpoints: list contacts, per-contact
interaction timeline (inbound + outbound), and the on-demand (never
automatic) AI relationship summary.
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


def test_list_contacts_includes_company_name():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.company import Company, Contact

        db = SessionLocal()
        company = Company(name="創意ラボ株式会社", domain="soilab.jp")
        db.add(company)
        db.flush()
        contact = Contact(company_id=company.id, name="遠藤様", email_address="sales@soilab.jp", source="email")
        db.add(contact)
        db.commit()
        db.close()

        resp = client.get("/contacts")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["company_name"] == "創意ラボ株式会社"
        assert body[0]["email_address"] == "sales@soilab.jp"


def test_contact_timeline_includes_inbound_and_outbound_messages():
    with _make_client() as client:
        import json

        from app.db.session import SessionLocal
        from app.db.models.company import Contact
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="me@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        contact = Contact(name="遠藤様", email_address="sales@soilab.jp", source="email")
        db.add(contact)
        db.add(
            Message(
                account_id=account.id, message_uid="1", folder="INBOX", subject="案件のご紹介",
                sender_address="sales@soilab.jp",
            )
        )
        db.add(
            Message(
                account_id=account.id, message_uid="2", folder="Sent", subject="Re: 案件のご紹介",
                sender_address="me@example.com", to_addresses=json.dumps(["sales@soilab.jp"]),
            )
        )
        db.commit()
        contact_id = contact.id
        db.close()

        resp = client.get(f"/contacts/{contact_id}/timeline")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        directions = {e["direction"] for e in body}
        assert directions == {"inbound", "outbound"}


def test_timeline_404s_for_unknown_contact():
    with _make_client() as client:
        resp = client.get("/contacts/does-not-exist/timeline")
        assert resp.status_code == 404


def test_summarize_contact_with_no_history_does_not_call_llm():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.company import Contact

        db = SessionLocal()
        contact = Contact(name="誰か", email_address="nobody@example.com", source="email")
        db.add(contact)
        db.commit()
        contact_id = contact.id
        db.close()

        resp = client.post(f"/contacts/{contact_id}/summarize")
        assert resp.status_code == 200
        assert "まだやり取りの記録がありません" in resp.json()["summary"]
