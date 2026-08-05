from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.ai import AIAnalysis
from app.db.models.company import Company
from app.db.models.deal import Candidate, Deal
from app.db.models.email import Message

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardOut(BaseModel):
    deals_today: int
    candidates_today: int
    reply_required_open: int
    open_deal_count: int
    open_candidate_count: int
    top_companies: list[dict]


@router.get("", response_model=DashboardOut)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardOut:
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    deals_today = db.query(Deal).filter(Deal.created_at >= today_start).count()
    candidates_today = db.query(Candidate).filter(Candidate.created_at >= today_start).count()
    open_deal_count = db.query(Deal).filter(Deal.status == "open").count()
    open_candidate_count = db.query(Candidate).filter(Candidate.status == "open").count()

    reply_required_open = 0
    for analysis in db.query(AIAnalysis).filter(AIAnalysis.classification_json != "{}").all():
        try:
            data = json.loads(analysis.classification_json)
        except json.JSONDecodeError:
            continue
        if data.get("reply_required"):
            reply_required_open += 1

    top_companies_rows = (
        db.query(Company.name, Company.deal_count)
        .order_by(Company.deal_count.desc())
        .limit(5)
        .all()
    )

    return DashboardOut(
        deals_today=deals_today,
        candidates_today=candidates_today,
        reply_required_open=reply_required_open,
        open_deal_count=open_deal_count,
        open_candidate_count=open_candidate_count,
        top_companies=[{"name": name, "deal_count": count} for name, count in top_companies_rows],
    )
