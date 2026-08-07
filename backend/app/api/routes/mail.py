from __future__ import annotations

import imaplib
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.db.models.ai import AIAnalysis, AuditLogEntry
from app.db.models.company import Company, Contact
from app.db.models.deal import Candidate, Deal
from app.db.models.email import Attachment, EmailAccount, Message
from app.db.models.meeting import Meeting
from app.services import business_card_service
from app.services.mail import smtp_client, sync_service
from app.services.mail.html_text import html_to_text, looks_like_html
from app.services.mail.threading_service import get_or_create_thread

router = APIRouter(prefix="/mail", tags=["mail"])


class MessageOut(BaseModel):
    id: str
    account_id: str
    account_email_address: str
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
    to_addresses: list[str] = []
    cc_addresses: list[str] = []
    classification: dict | None = None
    extraction: dict | None = None
    summary_3line: str | None = None
    attachments: list[AttachmentOut] = []
    is_fallback: bool = False
    provider_used: str | None = None
    fallback_reason: str | None = None


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


_VIEW_ONLINE_STUB_MIN_CHARS = 150
_VIEW_ONLINE_STUB_RATIO = 1.5


def _display_body_text(message: Message) -> str:
    """Repairs messages synced before the imap_client HTML/plain-text fix
    (see services/mail/html_text.py): those have raw HTML markup sitting in
    body_text with body_html empty. Computed at read time rather than in a
    migration so it also self-heals if the sniff heuristic improves later.

    Separately: mass-mail ASPs (cuenote and similar) commonly send a
    multipart/alternative message whose text/plain part is intentionally
    just a one-or-two-line "メールがうまく表示されない方はこちらをご覧く
    ださい" stub with a tracking link, while the actual content — the job
    listing, the案件 details, everything the recipient actually needs to
    read — only exists in the text/html part. imap_client correctly stores
    both parts, but nothing ever displayed body_html, so the mail looked
    empty/broken in MailSort while rendering fine in a client (Outlook)
    that shows HTML mail. When the html-derived text is clearly the
    substantive version (much longer than the plain-text part), prefer it."""
    if looks_like_html(message.body_text) and not message.body_html:
        return html_to_text(message.body_text)
    if message.body_html:
        html_derived = html_to_text(message.body_html)
        if len(html_derived) > _VIEW_ONLINE_STUB_MIN_CHARS and len(html_derived) > len(message.body_text.strip()) * _VIEW_ONLINE_STUB_RATIO:
            return html_derived
    return message.body_text


@router.get("/folders", response_model=list[str])
def list_local_folders(db: Session = Depends(get_db)) -> list[str]:
    """Distinct Message.folder values actually in use — lets the sidebar
    show any folder a rule's "move_to_folder" action routes into, not just
    the fixed 案件/人材/重要/要返信/Junk set the built-in classification
    heuristic knows about (custom rule folder names are free text)."""
    rows = db.query(Message.folder).distinct().all()
    return sorted({folder for (folder,) in rows if folder})


@router.get("", response_model=list[MessageOut])
def list_messages(
    folder: str = "INBOX",
    account_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Message]:
    q = db.query(Message).options(joinedload(Message.account)).filter(Message.folder == folder)
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

    def _parse_addresses(raw: str) -> list[str]:
        try:
            return json.loads(raw) if raw else []
        except json.JSONDecodeError:
            return []

    return MessageDetailOut(
        **MessageOut.model_validate(message).model_dump(),
        body_text=_display_body_text(message),
        body_html=message.body_html,
        to_addresses=_parse_addresses(message.to_addresses),
        cc_addresses=_parse_addresses(message.cc_addresses),
        classification=json.loads(analysis.classification_json) if analysis and analysis.classification_json else None,
        extraction=json.loads(analysis.extraction_json) if analysis and analysis.extraction_json else None,
        summary_3line=analysis.summary_3line if analysis else None,
        attachments=[AttachmentOut.model_validate(a) for a in message.attachments],
        is_fallback=analysis.is_fallback if analysis else False,
        provider_used=analysis.provider_used if analysis else None,
        fallback_reason=analysis.fallback_reason if analysis else None,
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
    if not account.imap_host:
        raise HTTPException(status_code=400, detail="account has no imap_host configured")
    try:
        return await sync_service.sync_account(db, account, folder=folder, limit=limit)
    except (imaplib.IMAP4.error, OSError) as exc:
        # A real connection failure (bad host/port, wrong credentials, TLS
        # mismatch, or the server just dropping the connection) used to
        # propagate as an unhandled 500 with a raw traceback — the "今すぐ
        # 受信" button just showed a generic network error with nothing the
        # user could act on, for the exact class of problem (account
        # misconfiguration) that most needs a clear message.
        raise HTTPException(status_code=502, detail=f"IMAPサーバーへの接続に失敗しました: {exc}") from exc


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


@router.put("/draft/{message_id}", response_model=MessageOut)
def update_draft(message_id: str, payload: DraftCreate, db: Session = Depends(get_db)) -> Message:
    """Updates an existing draft in place (used by "編集を続ける" in the UI)
    instead of the old behavior of only ever being able to create a new
    draft — every incremental save used to leave the previous version
    behind as an orphaned Drafts-folder row."""
    message = db.query(Message).filter(Message.id == message_id, Message.folder == "Drafts").one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="draft not found")

    message.account_id = payload.account_id
    message.subject = payload.subject
    message.to_addresses = json.dumps(payload.to, ensure_ascii=False)
    message.cc_addresses = json.dumps(payload.cc, ensure_ascii=False)
    message.body_text = payload.body_text
    db.commit()
    db.refresh(message)
    return message


@router.post("/{message_id}/send")
def send_reply(message_id: str, payload: SendRequest, db: Session = Depends(get_db)) -> dict:
    """Sends a reply to an existing message, or — when message_id points at
    a Drafts-folder message — sends that draft, after which the draft row
    is deleted (its content now lives on as the Sent-folder copy below)."""
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

    # Record the sent message as a Message (folder="Sent") in the same
    # thread as the message it replies to (or a fresh thread, for a
    # from-scratch draft). Previously sent mail vanished from the DB
    # entirely once smtplib returned — this is also what makes
    # reply-rate / response-speed dashboard insights computable (see
    # services/insights_service.py).
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

    was_draft = message.folder == "Drafts"
    if was_draft:
        db.delete(message)

    db.commit()

    return {"status": "sent"}
