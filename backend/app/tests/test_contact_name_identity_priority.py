"""Real user report: the Contacts page showed dozens of genuinely different
companies (proud-g.jp, tdc.co.jp, sie.co.jp, bbreak.co.jp, ...) all sharing
the exact same contact name. Root cause: upsert_company_and_contact
prioritized extraction.contact_name (the AI's freeform guess at "who this
email is about," read from the body) over message.sender_name (parsed from
the reliable IMAP From: header). Templated bulk-recruitment mail sent on
behalf of many different companies often has an identical signature/footer
block in the body, so every message's AI-extracted contact_name collapsed
to that one shared name regardless of which company's own domain actually
sent it. message.sender_name is a structurally reliable per-message signal
that can't collide across unrelated senders the way a body-text guess can,
so it now takes priority."""
from __future__ import annotations

from app.db.models.company import Company, Contact
from app.db.models.email import EmailAccount, Message
from app.schemas.extraction import ExtractionResult
from app.services.company_aggregation_service import upsert_company_and_contact


def _make_message(db_session, *, sender_name: str, sender_address: str) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(
        account_id=account.id, message_uid="1", subject="件名", sender_name=sender_name, sender_address=sender_address
    )
    db_session.add(message)
    db_session.commit()
    return message


def test_reproduces_the_exact_reported_bug_across_unrelated_companies(db_session):
    """Two totally unrelated companies both had a templated bulk-recruitment
    email whose body signed off as "遠藤奨太" — extraction.contact_name
    picks that up identically for both. Their real per-company sender
    identity (parsed from each one's own From: header) must win instead,
    or their Contact rows collide on an identical, meaningless name."""
    message_a = _make_message(db_session, sender_name="石橋 史織", sender_address="ishii_shi@tdc.co.jp")
    extraction_a = ExtractionResult.model_validate({"contact_name": "遠藤 奨太"})
    upsert_company_and_contact(db_session, message_a, extraction_a)

    message_b = _make_message(db_session, sender_name="篠崎", sender_address="shinozaki@bbreak.co.jp")
    extraction_b = ExtractionResult.model_validate({"contact_name": "遠藤 奨太"})
    upsert_company_and_contact(db_session, message_b, extraction_b)

    contact_a = db_session.query(Contact).filter(Contact.email_address == "ishii_shi@tdc.co.jp").one()
    contact_b = db_session.query(Contact).filter(Contact.email_address == "shinozaki@bbreak.co.jp").one()
    assert contact_a.name == "石橋 史織"
    assert contact_b.name == "篠崎"
    assert contact_a.name != contact_b.name


def test_ai_extracted_contact_name_is_still_used_when_the_header_has_no_display_name(db_session):
    message = _make_message(db_session, sender_name="", sender_address="sales@vendor.example")
    extraction = ExtractionResult.model_validate({"contact_name": "山田太郎"})

    upsert_company_and_contact(db_session, message, extraction)

    contact = db_session.query(Contact).filter(Contact.email_address == "sales@vendor.example").one()
    assert contact.name == "山田太郎"


def test_sender_name_wins_even_when_updating_an_already_existing_contact(db_session):
    message = _make_message(db_session, sender_name="本物の担当者", sender_address="sales@vendor.example")
    company = Company(name="Vendor", domain="vendor.example")
    db_session.add(company)
    db_session.flush()
    db_session.add(Contact(company_id=company.id, name="旧名", email_address="sales@vendor.example"))
    db_session.commit()

    extraction = ExtractionResult.model_validate({"contact_name": "テンプレート署名の人物"})
    upsert_company_and_contact(db_session, message, extraction)

    contact = db_session.query(Contact).filter(Contact.email_address == "sales@vendor.example").one()
    assert contact.name == "本物の担当者"
