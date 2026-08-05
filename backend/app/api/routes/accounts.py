from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.security import encrypt_secret
from app.db.models.email import EmailAccount

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


@router.delete("/{account_id}")
def delete_account(account_id: str, db: Session = Depends(get_db)) -> dict:
    account = db.query(EmailAccount).filter(EmailAccount.id == account_id).one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="account not found")
    db.delete(account)
    db.commit()
    return {"status": "deleted"}
