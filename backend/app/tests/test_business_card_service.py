from __future__ import annotations

import pytest

from app.db.models.company import Company, Contact
from app.services import business_card_service


@pytest.mark.asyncio
async def test_extract_fields_regex_fallback_finds_email_and_phone():
    text = "株式会社サンプル\n営業部 田中太郎\nTEL: 03-1234-5678\ntanaka@example.com"
    fields = await business_card_service.extract_fields(text)
    assert fields.email == "tanaka@example.com"
    assert fields.phone == "03-1234-5678"


@pytest.mark.asyncio
async def test_extract_fields_empty_text_returns_empty_fields():
    fields = await business_card_service.extract_fields("")
    assert fields == business_card_service.BusinessCardFields()


def test_upsert_from_business_card_creates_company_and_contact(db_session):
    fields = business_card_service.BusinessCardFields(
        company_name="株式会社サンプル",
        department="営業部",
        name="田中太郎",
        title="部長",
        email="tanaka@example.com",
        phone="03-1234-5678",
    )
    contact = business_card_service.upsert_from_business_card(db_session, fields)

    assert contact.name == "田中太郎"
    assert contact.email_address == "tanaka@example.com"
    assert contact.source == "business_card_ocr"

    company = db_session.query(Company).filter(Company.name == "株式会社サンプル").one()
    assert contact.company_id == company.id


def test_upsert_from_business_card_matches_existing_contact_by_email(db_session):
    company = Company(name="既存会社")
    db_session.add(company)
    db_session.flush()
    existing = Contact(company_id=company.id, name="旧名前", email_address="tanaka@example.com", source="email")
    db_session.add(existing)
    db_session.commit()

    fields = business_card_service.BusinessCardFields(
        company_name="既存会社", name="田中太郎（新）", email="tanaka@example.com", title="課長"
    )
    contact = business_card_service.upsert_from_business_card(db_session, fields)

    assert contact.id == existing.id
    assert contact.name == "田中太郎（新）"
    assert contact.title == "課長"
    assert contact.source == "business_card_ocr"

    assert db_session.query(Contact).filter(Contact.email_address == "tanaka@example.com").count() == 1


def test_upsert_from_business_card_without_email_creates_new_contact_each_time(db_session):
    fields = business_card_service.BusinessCardFields(name="名刺のみの担当者", phone="090-0000-0000")
    contact1 = business_card_service.upsert_from_business_card(db_session, fields)
    contact2 = business_card_service.upsert_from_business_card(db_session, fields)

    assert contact1.id != contact2.id  # no email to key off of, so no dedup is attempted
