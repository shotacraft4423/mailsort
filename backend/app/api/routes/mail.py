from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.ai import AIAnalysis, AuditLogEntry
from app.db.models.company import Company, Contact
from app.db.models.deal import Candidate, Deal
from app.db.models.email import Attachment, EmailAccount, Message
from app.db.models.meeting import Meeting
from app.services import business_card_service
from app.services.mail import smtp_client, sync_service
from app.services.mail.threading_service import get_or_create_thread

router = APIRouter(prefix="/mail", tags=["mail"])


class MessageOut(BaseModel):
    id: str
    account_id: str
    folder: str
    subject: str
    sender_name: str
    sender_address: str
    is_read: bool
    is_flagged: bool
    received_at: datetime | None

    model_config = {"from_attributes": True}


class AttachmentOut(BaseModel):
    id: str
    file_name: str
    content_type: str
    size_bytes: int
    classified_kind: str | None

    model_config = {"from_attributes": True}


class MessageDetailOut(MessageOut):
    body_text: str
    body_html: str
    classification: dict | None = None
    extraction: dict | None = None
    summary_3line: str | None = None
    attachments: list[AttachmentOut] = []


class DraftCreate(BaseModel):
    account_id: str
    to: list[str]
    cc: list[str] = []
    subject: str
    body_text: str


class SendRequest(BaseModel):
    to: list[str]
    cc: list[str] = []
    subject: str
    body_text: str
    in_reply_to: str | None = None


@router.get("", response_model=list[MessageOut])
def list_messages(
    folder: str = "INBOX",
    account_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Message]:
    q = db.query(Message).filter(Message.folder == folder)
    if account_id:
        q = q.filter(Message.account_id == account_id)
    return q.order_by(Message.received_at.desc()).offset(offset).limit(limit).all()


@router.get("/{message_id}", response_model=MessageDetailOut)
def get_message(message_id: str, db: Session = Depends(get_db)) -> MessageDetailOut:
    message = db.query(Message).filter(Message.id == message_id).one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")

    # Standard mail-client behavior: opening a message marks it read. This
    # was previously never set anywhere outside the Sent-copy path, so
    # every inbound message stayed "unread" forever regardless of use.
    if not message.is_read:
        message.is_read = True
        db.commit()

    analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message_id).one_or_none()
    return MessageDetailOut(
        **MessageOut.model_validate(message).model_dump(),
        body_text=message.body_text,
        body_html=message.body_html,
        classification=json.loads(analysis.classification_json) if analysis and analysis.classification_json else None,
        extraction=json.loads(analysis.extraction_json) if analysis and analysis.extraction_json else None,
        summary_3line=analysis.summary_3line if analysis else None,
        attachments=[AttachmentOut.model_validate(a) for a in message.attachments],
    )


class MessageUpdate(BaseModel):
    is_read: bool | None = None
    is_flagged: bool | None = None
    folder: str | None = None  # e.g. move to "Archive" / "Trash" / back to "INBOX"


@router.patch("/{message_id}", response_model=MessageOut)
def update_message(message_id: str, payload: MessageUpdate, db: Session = Depends(get_db)) -> Message:
    message = db.query(Message).filter(Message.id == message_id).one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")

    if payload.is_read is not None:
        message.is_read = payload.is_read
    if payload.is_flagged is not None:
        message.is_flagged = payload.is_flagged
    if payload.folder is not None:
        message.folder = payload.folder

    db.commit()
    db.refresh(message)
    return message


class RelatedCompanyOut(BaseModel):
    id: str
    name: str
    evaluation: str | None
    deal_count: int
    candidate_count: int
    last_contact_at: datetime | None

    model_config = {"from_attributes": True}


class RelatedOut(BaseModel):
    company: RelatedCompanyOut | None
    deals: list[dict]
    candidates: list[dict]
    meetings: list[dict]


@router.get("/{message_id}/related", response_model=RelatedOut)
def get_related(message_id: str, db: Session = Depends(get_db)) -> RelatedOut:
    """Everything the AI panel's 会社情報/案件情報/人材情報/会議 tabs need for
    one message, in a single round trip: the counterparty (matched by sender
    domain) plus any Deal/Candidate/Meeting rows this message produced."""
    message = db.query(Message).filter(Message.id == message_id).one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")

    company = None
    if "@" in message.sender_address:
        domain = message.sender_address.rsplit("@", 1)[-1].lower()
        company = db.query(Company).filter(Company.domain == domain).one_or_none()

    deals = db.query(Deal).filter(Deal.source_message_id == message_id).all()
    candidates = db.query(Candidate).filter(Candidate.source_message_id == message_id).all()
    meetings = db.query(Meeting).filter(Meeting.source_message_id == message_id).all()

    return RelatedOut(
        company=RelatedCompanyOut.model_validate(company) if company else None,
        deals=[
            {
                "id": d.id,
                "title": d.title,
                "unit_price_min": d.unit_price_min,
                "unit_price_max": d.unit_price_max,
                "location": d.location,
                "status": d.status,
            }
            for d in deals
        ],
        candidates=[
            {
                "id": c.id,
                "display_name": c.display_name,
                "unit_price_min": c.unit_price_min,
                "unit_price_max": c.unit_price_max,
                "location_preference": c.location_preference,
                "status": c.status,
            }
            for c in candidates
        ],
        meetings=[
            {
                "id": m.id,
                "title": m.title,
                "platform": m.platform,
                "join_url": m.join_url,
                "starts_at": m.starts_at.isoformat() if m.starts_at else None,
                "is_rescheduled": m.is_rescheduled,
            }
            for m in meetings
        ],
    )


class AuditLogEntryOut(BaseModel):
    id: str
    action: str
    provider_used: str
    rationale: str
    data_sent_summary: str
    anonymized: bool
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/{message_id}/audit-log", response_model=list[AuditLogEntryOut])
def get_audit_log(message_id: str, db: Session = Depends(get_db)) -> list[AuditLogEntry]:
    """"AIがなぜこのメールをこう判断したか" — every AI decision made about
    this message (classification, extraction, rule fires, ...), newest
    first, so a user can see the rationale and what data was sent."""
    return (
        db.query(AuditLogEntry)
        .filter(AuditLogEntry.message_id == message_id)
        .order_by(AuditLogEntry.created_at.desc())
        .all()
    )


class BusinessCardContactOut(BaseModel):
    id: str
    company_id: str | None
    name: str
    email_address: str
    phone: str | None
    department: str | None
    title: str | None

    model_config = {"from_attributes": True}


@router.post("/attachments/{attachment_id}/register-business-card", response_model=BusinessCardContactOut)
async def register_business_card(attachment_id: str, db: Session = Depends(get_db)) -> Contact:
    """名刺OCR → CRM登録: uses the attachment's already-OCR'd text (see
    attachment_analysis_service; empty if tesseract isn't installed) to
    extract contact fields and upsert a Company/Contact pair."""
    attachment = db.query(Attachment).filter(Attachment.id == attachment_id).one_or_none()
    if attachment is None:
        raise HTTPException(status_code=404, detail="attachment not found")

    fields = await business_card_service.extract_fields(attachment.extracted_text or "")
    return business_card_service.upsert_from_business_card(db, fields)


@router.post("/accounts/{account_id}/sync", response_model=list[MessageOut])
async def sync_account(account_id: str, folder: str = "INBOX", limit: int = 50, db: Session = Depends(get_db)) -> list[Message]:
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id).one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    return await sync_service.sync_account(db, account, folder=folder, limit=limit)


@router.post("/draft", response_model=MessageOut)
def save_draft(payload: DraftCreate, db: Session = Depends(get_db)) -> Message:
    message = Message(
        account_id=payload.account_id,
        folder="Drafts",
        message_uid=f"draft-{payload.subject}-{len(payload.body_text)}",
        subject=payload.subject,
        sender_address="",
        to_addresses=json.dumps(payload.to, ensure_ascii=False),
        cc_addresses=json.dumps(payload.cc, ensure_ascii=False),
        body_text=payload.body_text,
        is_draft=True,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


@router.post("/{message_id}/send")
def send_reply(message_id: str, payload: SendRequest, db: Session = Depends(get_db)) -> dict:
    message = db.query(Message).filter(Message.id == message_id).one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    account = db.query(EmailAccount).filter(EmailAccount.id == message.account_id).one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")

    smtp_client.send_message(
        account,
        to=payload.to,
        cc=payload.cc,
        subject=payload.subject,
        body_text=payload.body_text,
        in_reply_to=payload.in_reply_to,
    )

    # Record the sent reply as a Message (folder="Sent") in the same
    # thread as the message it replies to. Previously sent mail vanished
    # from the DB entirely once smtplib returned — this is also what
    # makes reply-rate / response-speed dashboard insights computable
    # (see services/insights_service.py).
    thread_id = message.thread_id or get_or_create_thread(db, account.id, message.subject).id
    if message.thread_id is None:
        message.thread_id = thread_id

    sent_message = Message(
        account_id=account.id,
        thread_id=thread_id,
        folder="Sent",
        message_uid=f"sent-{message.id}-{datetime.utcnow().timestamp()}",
        subject=payload.subject,
        sender_name=account.display_name,
        sender_address=account.email_address,
        to_addresses=json.dumps(payload.to, ensure_ascii=False),
        cc_addresses=json.dumps(payload.cc or [], ensure_ascii=False),
        body_text=payload.body_text,
        received_at=datetime.utcnow(),
        is_read=True,
    )
    db.add(sent_message)
    db.commit()

    return {"status": "sent"}
