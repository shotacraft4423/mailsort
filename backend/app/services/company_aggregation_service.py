"""Upserts Company/Contact rows from a Message + its ExtractionResult, and
keeps the rolled-up stats (last_contact_at, deal_count, ...) current. Called
after extraction_service.extract_message succeeds; never blocks on AI being
available since it only needs the sender address for the minimal path."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.company import Company, Contact
from app.db.models.email import Message
from app.schemas.extraction import ExtractionResult


def _domain_of(address: str) -> str | None:
    if "@" not in address:
        return None
    return address.rsplit("@", 1)[-1].lower()


def upsert_company_and_contact(db: Session, message: Message, extraction: ExtractionResult | None) -> Company:
    domain = _domain_of(message.sender_address)
    name = (extraction.company_name if extraction else None) or (domain or message.sender_address or "不明な会社")

    # .first() rather than .one_or_none(): this is a best-effort upsert
    # keyed on loosely-derived values (domain, or a name that falls back
    # to the raw sender address / "不明な会社" when nothing better is
    # extracted), so two genuinely different messages can easily collide
    # on the same domain/name — that used to raise MultipleResultsFound
    # and crash the whole /ai/messages/{id}/analyze call the moment more
    # than a handful of messages had been aggregated.
    company = None
    if domain:
        company = db.query(Company).filter(Company.domain == domain).first()
    if company is None:
        company = db.query(Company).filter(Company.name == name).first()
    if company is None:
        company = Company(name=name, domain=domain)
        db.add(company)
        db.flush()

    company.last_contact_at = message.received_at or datetime.utcnow()

    contact_name = (extraction.contact_name if extraction else None) or message.sender_name
    if message.sender_address:
        contact = (
            db.query(Contact)
            .filter(Contact.company_id == company.id, Contact.email_address == message.sender_address)
            .first()
        )
        if contact is None:
            contact = Contact(
                company_id=company.id,
                name=contact_name or "",
                email_address=message.sender_address,
                phone=(extraction.phone if extraction else None),
            )
            db.add(contact)
        else:
            if contact_name:
                contact.name = contact_name
            if extraction and extraction.phone:
                contact.phone = extraction.phone

    db.commit()
    db.refresh(company)
    return company
