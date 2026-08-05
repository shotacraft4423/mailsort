from __future__ import annotations

import asyncio
import imaplib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.security import encrypt_secret
from app.db.models.email import EmailAccount
from app.services.mail.imap_client import ImapConnector

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    display_name: str
    email_address: str
    protocol: str = "imap_smtp"
    imap_host: str | None = None
    imap_port: int | None = 993
    smtp_host: str | None = None
    smtp_port: int | None = 465
    use_ssl: bool = True
    password: str | None = None
    forced_llm_provider: str | None = None


class AccountOut(BaseModel):
    id: str
    display_name: str
    email_address: str
    protocol: str
    is_active: bool
    forced_llm_provider: str | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)) -> list[EmailAccount]:
    return db.query(EmailAccount).all()


@router.post("", response_model=AccountOut)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)) -> EmailAccount:
    account = EmailAccount(
        display_name=payload.display_name,
        email_address=payload.email_address,
        protocol=payload.protocol,
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        use_ssl=payload.use_ssl,
        credential_encrypted=encrypt_secret(payload.password) if payload.password else None,
        forced_llm_provider=payload.forced_llm_provider,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.get("/{account_id}/folders", response_model=list[str])
async def list_folders(account_id: str, db: Session = Depends(get_db)) -> list[str]:
    """Real IMAP folder listing (LIST command), replacing what used to be a
    hardcoded folder list in the frontend. Runs the blocking imaplib call in
    a worker thread, same as sync — a real IMAP round trip, so this is also
    the first place account misconfiguration (bad host/credentials) shows
    up as a clear error rather than a mysterious empty inbox."""
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id).one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    if not account.imap_host:
        raise HTTPException(status_code=400, detail="account has no imap_host configured")

    try:
        return await asyncio.to_thread(ImapConnector(account).list_folders)
    except (imaplib.IMAP4.error, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"IMAPサーバーへの接続に失敗しました: {exc}") from exc


@router.delete("/{account_id}")
def delete_account(account_id: str, db: Session = Depends(get_db)) -> dict:
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id).one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    db.delete(account)
    db.commit()
    return {"status": "deleted"}
