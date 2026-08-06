from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.company import Company, Contact
from app.services.contact_timeline_service import build_timeline, summarize_relationship

router = APIRouter(prefix="/contacts", tags=["contacts"])


class ContactOut(BaseModel):
    id: str
    company_id: str | None
    company_name: str | None
    name: str
    email_address: str
    phone: str | None
    department: str | None
    title: str | None
    source: str


class TimelineEntryOut(BaseModel):
    message_id: str
    subject: str
    direction: str
    folder: str
    received_at: datetime | None
    summary: str | None
    top_category: str | None


class SummarizeOut(BaseModel):
    summary: str


def _get_contact(db: Session, contact_id: str) -> Contact:
    contact = db.query(Contact).filter(Contact.id == contact_id).one_or_none()
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found")
    return contact


@router.get("", response_model=list[ContactOut])
def list_contacts(db: Session = Depends(get_db)) -> list[ContactOut]:
    contacts = db.query(Contact).order_by(Contact.name).all()
    company_names = {c.id: c.name for c in db.query(Company).all()}
    return [
        ContactOut(
            id=c.id,
            company_id=c.company_id,
            company_name=company_names.get(c.company_id) if c.company_id else None,
            name=c.name,
            email_address=c.email_address,
            phone=c.phone,
            department=c.department,
            title=c.title,
            source=c.source,
        )
        for c in contacts
    ]


@router.get("/{contact_id}/timeline", response_model=list[TimelineEntryOut])
def get_timeline(contact_id: str, db: Session = Depends(get_db)) -> list[TimelineEntryOut]:
    contact = _get_contact(db, contact_id)
    return [TimelineEntryOut(**vars(e)) for e in build_timeline(db, contact)]


@router.post("/{contact_id}/summarize", response_model=SummarizeOut)
async def summarize_contact(contact_id: str, db: Session = Depends(get_db)) -> SummarizeOut:
    contact = _get_contact(db, contact_id)
    entries = build_timeline(db, contact)
    return SummarizeOut(summary=await summarize_relationship(contact, entries))
