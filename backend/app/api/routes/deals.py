from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.company import Company
from app.db.models.deal import Candidate, Deal, MatchScore
from app.services.duplicate_detection_service import find_duplicate_deals, persist_deal_duplicates
from app.services.matching_service import find_matches_for_deal

router = APIRouter(prefix="/deals", tags=["deals"])


class DealOut(BaseModel):
    id: str
    title: str
    company_id: str | None
    location: str | None
    unit_price_min: int | None
    unit_price_max: int | None
    status: str
    duplicate_of_id: str | None
    duplicate_relation: str | None

    model_config = {"from_attributes": True}


class DealCreate(BaseModel):
    title: str
    company_id: str | None = None
    skills: list[str] = []
    location: str | None = None
    unit_price_min: int | None = None
    unit_price_max: int | None = None
    period: str | None = None
    headcount: int | None = None
    business_flow: str | None = None
    work_style: str | None = None


@router.get("", response_model=list[DealOut])
def list_deals(status: str | None = None, db: Session = Depends(get_db)) -> list[Deal]:
    q = db.query(Deal)
    if status:
        q = q.filter(Deal.status == status)
    return q.order_by(Deal.created_at.desc()).all()


@router.post("", response_model=DealOut)
def create_deal(payload: DealCreate, db: Session = Depends(get_db)) -> Deal:
    deal = Deal(
        title=payload.title,
        company_id=payload.company_id,
        skills_json=json.dumps(payload.skills, ensure_ascii=False),
        location=payload.location,
        unit_price_min=payload.unit_price_min,
        unit_price_max=payload.unit_price_max,
        period=payload.period,
        headcount=payload.headcount,
        business_flow=payload.business_flow,
        work_style=payload.work_style,
    )
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return deal


@router.post("/{deal_id}/find-duplicates")
async def find_duplicates(deal_id: str, db: Session = Depends(get_db)) -> list[dict]:
    deal = db.query(Deal).filter(Deal.id == deal_id).one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="deal not found")
    matches = await find_duplicate_deals(db, deal)
    persist_deal_duplicates(db, deal, matches)
    return [
        {"other_id": m.other_id, "similarity": m.similarity, "relation": m.relation, "reason": m.reason}
        for m in matches
    ]


@router.get("/{deal_id}/network")
def get_network(deal_id: str, db: Session = Depends(get_db)) -> dict:
    """重複案件ネットワーク表示: the full duplicate cluster this deal belongs
    to (itself if it's the cluster root, or its root + siblings otherwise),
    with company name and price per member so the UI can show how many
    companies are distributing what looks like the same opportunity."""
    deal = db.query(Deal).filter(Deal.id == deal_id).one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="deal not found")

    root_id = deal.duplicate_of_id or deal.id
    root = db.query(Deal).filter(Deal.id == root_id).one_or_none()
    members = db.query(Deal).filter(Deal.duplicate_of_id == root_id).all()
    if root is None:
        return {"root_id": root_id, "nodes": [], "company_count": 0}

    all_deals = [root, *members]
    company_ids = {d.company_id for d in all_deals if d.company_id}
    companies = {c.id: c.name for c in db.query(Company).filter(Company.id.in_(company_ids)).all()}

    def to_node(d: Deal, *, is_root: bool) -> dict:
        return {
            "id": d.id,
            "title": d.title,
            "company_name": companies.get(d.company_id, "不明な会社"),
            "unit_price_min": d.unit_price_min,
            "unit_price_max": d.unit_price_max,
            "business_flow": d.business_flow,
            "relation": "root" if is_root else (d.duplicate_relation or "candidate"),
        }

    nodes = [to_node(root, is_root=True)] + [to_node(m, is_root=False) for m in members]
    return {
        "root_id": root_id,
        "nodes": nodes,
        "company_count": len({n["company_name"] for n in nodes}),
    }


@router.post("/{deal_id}/find-matches")
async def find_matches(deal_id: str, top_n: int = 5, db: Session = Depends(get_db)) -> list[dict]:
    deal = db.query(Deal).filter(Deal.id == deal_id).one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="deal not found")
    results = await find_matches_for_deal(db, deal, top_n=top_n)
    return [
        {
            "candidate_id": r.match.candidate_id,
            "score": r.match.score,
            "similarity": r.similarity,
            "rationale": r.match.rationale,
        }
        for r in results
    ]


@router.get("/{deal_id}/matches")
def get_matches(deal_id: str, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(MatchScore).filter(MatchScore.deal_id == deal_id).order_by(MatchScore.score.desc()).all()
    candidates = {c.id: c for c in db.query(Candidate).filter(Candidate.id.in_([r.candidate_id for r in rows])).all()}
    return [
        {
            "candidate_id": r.candidate_id,
            "candidate_name": candidates[r.candidate_id].display_name if r.candidate_id in candidates else "(削除済み)",
            "score": r.score,
            "rationale": r.rationale,
        }
        for r in rows
    ]
