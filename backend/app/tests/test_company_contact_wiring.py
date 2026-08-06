"""Regression coverage: company_aggregation_service.upsert_company_and_contact
existed with a docstring claiming it ran "after extraction_service.extract_
message succeeds", but nothing in the app ever called it — the AI panel's
会社情報 tab always showed "送信元ドメインに一致する会社情報がまだありません"
and no Contact rows were ever created from ordinary mail (only business
card OCR created any), regardless of how many messages were classified.
"""
from __future__ import annotations

import pytest

from app.db.models.company import Company, Contact
from app.db.models.email import EmailAccount, Message
from app.services import analysis_service


@pytest.mark.asyncio
async def test_analyze_message_creates_company_and_contact_from_sender(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="Java案件のご紹介",
        sender_name="営業太郎",
        sender_address="sales@vendor.example",
        body_text="Java案件のご紹介です。",
    )
    db_session.add(message)
    db_session.commit()

    await analysis_service.analyze_message(db_session, message)

    company = db_session.query(Company).filter(Company.domain == "vendor.example").one_or_none()
    assert company is not None
    contact = db_session.query(Contact).filter(Contact.email_address == "sales@vendor.example").one_or_none()
    assert contact is not None
    assert contact.company_id == company.id
