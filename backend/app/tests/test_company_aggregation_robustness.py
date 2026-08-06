"""Regression coverage for a real production failure: once
company_aggregation_service.upsert_company_and_contact started running at
scale (wired into analyze_message's cache-hit path so it fires for every
already-classified message, not just newly-synced ones), its `.one_or_none()`
lookups by Company.name / Contact.(company_id, email_address) raised
sqlalchemy.orm.exc.MultipleResultsFound the moment real, messy mail data
produced more than one row matching the same loosely-derived key (e.g. two
different senders both falling back to the same "不明な会社" company name).
That crashed the entire /ai/messages/{id}/analyze call — a user reported
"50件中50件失敗しました" running bulk-classify. Switched to `.first()`.
"""
from __future__ import annotations

from app.db.models.company import Company, Contact
from app.db.models.email import EmailAccount, Message
from app.services.company_aggregation_service import upsert_company_and_contact


def test_upsert_tolerates_pre_existing_duplicate_company_names(db_session):
    db_session.add(Company(name="不明な会社", domain=None))
    db_session.add(Company(name="不明な会社", domain=None))
    db_session.flush()

    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="no-domain-sender")
    db_session.add(message)
    db_session.commit()

    # Must not raise sqlalchemy.orm.exc.MultipleResultsFound.
    company = upsert_company_and_contact(db_session, message, None)
    assert company is not None


def test_upsert_tolerates_pre_existing_duplicate_contacts(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    company = Company(name="Vendor", domain="vendor.example")
    db_session.add(company)
    db_session.flush()
    db_session.add(Contact(company_id=company.id, name="太郎", email_address="sales@vendor.example"))
    db_session.add(Contact(company_id=company.id, name="太郎", email_address="sales@vendor.example"))
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="sales@vendor.example")
    db_session.add(message)
    db_session.commit()

    result = upsert_company_and_contact(db_session, message, None)
    assert result.id == company.id
