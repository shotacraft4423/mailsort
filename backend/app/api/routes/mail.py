from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.ai import AIAnalysis
from app.db.models.email import EmailAccount, Message
from app.services.mail import smtp_client, sync_service

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
    received_at: str | None

    model_config = {"from_attributes": True}


class MessageDetailOut(MessageOut):
    body_text: str
    body_html: str
    classification: dict | None = None
    extraction: dict | None = None
    summary_3line: str | None = None


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

    analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message_id).one_or_none()
    return MessageDetailOut(
        **MessageOut.model_validate(message).model_dump(),
        body_text=message.body_text,
        body_html=message.body_html,
        classification=json.loads(analysis.classification_json) if analysis and analysis.classification_json else None,
        extraction=json.loads(analysis.extraction_json) if analysis and analysis.extraction_json else None,
        summary_3line=analysis.summary_3line if analysis else None,
    )


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
    return {"status": "sent"}
