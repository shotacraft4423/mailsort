from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.deal import Candidate, Deal, MatchScore
from app.services.duplicate_detection_service import find_duplicate_candidates
from app.services.matching_service import find_matches_for_candidate

router = APIRouter(prefix="/candidates", tags=["candidates"])


class CandidateOut(BaseModel):
    id: str
    display_name: str
    company_id: str | None
    location_preference: str | None
    unit_price_min: int | None
    unit_price_max: int | None
    status: str
    duplicate_of_id: str | None
    duplicate_relation: str | None

    model_config = {"from_attributes": True}


class CandidateCreate(BaseModel):
    display_name: str
    company_id: str | None = None
    skills: list[str] = []
    age: int | None = None
    nationality: str | None = None
    unit_price_min: int | None = None
    unit_price_max: int | None = None
    location_preference: str | None = None
    business_flow: str | None = None


@router.get("", response_model=list[CandidateOut])
def list_candidates(status: str | None = None, db: Session = Depends(get_db)) -> list[Candidate]:
    q = db.query(Candidate)
    if status:
        q = q.filter(Candidate.status == status)
    return q.order_by(Candidate.created_at.desc()).all()


@router.post("", response_model=CandidateOut)
def create_candidate(payload: CandidateCreate, db: Session = Depends(get_db)) -> Candidate:
    candidate = Candidate(
        display_name=payload.display_name,
        company_id=payload.company_id,
        skills_json=json.dumps(payload.skills, ensure_ascii=False),
        age=payload.age,
        nationality=payload.nationality,
        unit_price_min=payload.unit_price_min,
        unit_price_max=payload.unit_price_max,
        location_preference=payload.location_preference,
        business_flow=payload.business_flow,
    )
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


@router.post("/{candidate_id}/find-duplicates")
async def find_duplicates(candidate_id: str, db: Session = Depends(get_db)) -> list[dict]:
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    matches = await find_duplicate_candidates(db, candidate)
    return [
        {"other_id": m.other_id, "similarity": m.similarity, "relation": m.relation, "reason": m.reason}
        for m in matches
    ]


@router.post("/{candidate_id}/find-matches")
async def find_matches(candidate_id: str, top_n: int = 5, db: Session = Depends(get_db)) -> list[dict]:
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).one_or_none()
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    results = await find_matches_for_candidate(db, candidate, top_n=top_n)
    return [
        {
            "deal_id": r.match.deal_id,
            "score": r.match.score,
            "similarity": r.similarity,
            "rationale": r.match.rationale,
        }
        for r in results
    ]


@router.get("/{candidate_id}/matches")
def get_matches(candidate_id: str, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(MatchScore).filter(MatchScore.candidate_id == candidate_id).order_by(MatchScore.score.desc()).all()
    deals = {d.id: d for d in db.query(Deal).filter(Deal.id.in_([r.deal_id for r in rows])).all()}
    return [
        {
            "deal_id": r.deal_id,
            "deal_title": deals[r.deal_id].title if r.deal_id in deals else "(削除済み)",
            "score": r.score,
            "rationale": r.rationale,
        }
        for r in rows
    ]
