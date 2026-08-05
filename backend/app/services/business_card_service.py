"""名刺OCR → CRM登録: given a business card's OCR'd text (already produced by
attachment_analysis_service._extract_image_ocr — see that module for why the
OCR step itself degrades to "" without a tesseract install), pulls out
company/department/name/title/email/phone/address and upserts Company/
Contact rows with Contact.source="business_card_ocr" (a field the model
reserved from the start but nothing ever set).

LLM-assisted when available — free-form card layouts are a poor fit for
regex — with a regex-only fallback (email/phone only) so a card is still
partially useful offline or when the API is down, consistent with the rest
of the AI pipeline's degrade-don't-break policy. This is a manual,
on-demand action (POST /mail/attachments/{id}/register-business-card), not
part of the automatic sync pipeline, so it never adds LLM cost to routine
mail ingestion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models.company import Company, Contact
from app.providers.llm.base import LLMProviderError
from app.providers.llm.registry import get_llm_provider

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"0\d{1,4}[-‐]\d{1,4}[-‐]\d{3,4}")

SYSTEM_PROMPT = (
    "名刺をOCRしたテキストから、会社名・部署・氏名・役職・メールアドレス・"
    "電話番号・住所を抽出してください。読み取れない項目はnullにしてください。"
    'JSON {"company_name": ..., "department": ..., "name": ..., "title": ..., '
    '"email": ..., "phone": ..., "address": ...} のみで返してください。'
)


@dataclass
class BusinessCardFields:
    company_name: str | None = None
    department: str | None = None
    name: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None


def _regex_fallback(text: str) -> BusinessCardFields:
    email_match = _EMAIL_RE.search(text)
    phone_match = _PHONE_RE.search(text)
    return BusinessCardFields(
        email=email_match.group() if email_match else None,
        phone=phone_match.group() if phone_match else None,
    )


async def extract_fields(text: str) -> BusinessCardFields:
    if not text.strip():
        return BusinessCardFields()

    fallback = _regex_fallback(text)
    try:
        provider = get_llm_provider()
        raw, _usage = await provider.complete_json(system_prompt=SYSTEM_PROMPT, user_prompt=text)
    except LLMProviderError:
        return fallback

    return BusinessCardFields(
        company_name=raw.get("company_name"),
        department=raw.get("department"),
        name=raw.get("name"),
        title=raw.get("title"),
        email=raw.get("email") or fallback.email,
        phone=raw.get("phone") or fallback.phone,
        address=raw.get("address"),
    )


def upsert_from_business_card(db: Session, fields: BusinessCardFields) -> Contact:
    """Matches an existing Contact by email when available (the one field
    likely to be stable across re-scans of the same card); otherwise
    creates a new one. Company is matched/created by exact name — no domain
    to key off of for a scanned card, unlike email-derived Company matching
    elsewhere (see company_aggregation_service)."""
    company = None
    if fields.company_name:
        company = db.query(Company).filter(Company.name == fields.company_name).one_or_none()
        if company is None:
            company = Company(name=fields.company_name)
            db.add(company)
            db.flush()

    contact = None
    if fields.email:
        contact = db.query(Contact).filter(Contact.email_address == fields.email).one_or_none()

    if contact is None:
        contact = Contact(
            company_id=company.id if company else None,
            name=fields.name or "",
            email_address=fields.email or "",
            phone=fields.phone,
            department=fields.department,
            title=fields.title,
            source="business_card_ocr",
        )
        db.add(contact)
    else:
        contact.name = fields.name or contact.name
        contact.phone = fields.phone or contact.phone
        contact.department = fields.department or contact.department
        contact.title = fields.title or contact.title
        if company:
            contact.company_id = company.id
        contact.source = "business_card_ocr"

    db.commit()
    db.refresh(contact)
    return contact
