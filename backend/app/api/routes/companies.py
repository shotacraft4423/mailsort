from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.company import Company, Contact
from app.db.models.deal import Candidate, Deal

router = APIRouter(prefix="/companies", tags=["companies"])


class ContactOut(BaseModel):
    id: str
    name: str
    email_address: str
    phone: str | None
    title: str | None

    model_config = {"from_attributes": True}


class CompanyOut(BaseModel):
    id: str
    name: str
    domain: str | None
    evaluation: str | None
    notes: str
    last_contact_at: datetime | None
    reply_rate: float | None
    deal_count: int
    candidate_count: int
    contract_count: int

    model_config = {"from_attributes": True}


class CompanyDetailOut(CompanyOut):
    contacts: list[ContactOut]
    deal_ids: list[str]
    candidate_ids: list[str]


@router.get("", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)) -> list[Company]:
    return db.query(Company).order_by(Company.last_contact_at.desc()).all()


@router.get("/{company_id}", response_model=CompanyDetailOut)
def get_company(company_id: str, db: Session = Depends(get_db)) -> CompanyDetailOut:
    company = db.query(Company).filter(Company.id == company_id).one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    deal_ids = [d.id for d in db.query(Deal).filter(Deal.company_id == company_id).all()]
    candidate_ids = [c.id for c in db.query(Candidate).filter(Candidate.company_id == company_id).all()]
    return CompanyDetailOut(
        **CompanyOut.model_validate(company).model_dump(),
        contacts=[ContactOut.model_validate(c) for c in company.contacts],
        deal_ids=deal_ids,
        candidate_ids=candidate_ids,
    )


class CompanyUpdate(BaseModel):
    evaluation: str | None = None
    notes: str | None = None


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(company_id: str, payload: CompanyUpdate, db: Session = Depends(get_db)) -> Company:
    company = db.query(Company).filter(Company.id == company_id).one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="company not found")
    if payload.evaluation is not None:
        company.evaluation = payload.evaluation
    if payload.notes is not None:
        company.notes = payload.notes
    db.commit()
    db.refresh(company)
    return company
