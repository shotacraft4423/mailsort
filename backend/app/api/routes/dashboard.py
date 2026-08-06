from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.ai import AIAnalysis
from app.db.models.company import Company
from app.db.models.deal import Candidate, Deal
from app.services.insights_service import compute_insights, compute_reminders

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardOut(BaseModel):
    deals_today: int
    candidates_today: int
    reply_required_open: int
    open_deal_count: int
    open_candidate_count: int
    top_companies: list[dict]

    # 営業インサイト (DESIGN.md differentiator list). None means "not enough
    # data yet" rather than 0, so the UI can show "データ不足" instead of a
    # misleading zero.
    reply_rate: float | None
    avg_reply_speed_hours: float | None
    deal_win_rate: float | None
    weekly_contact_frequency: float


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

    insights = compute_insights(db)

    return DashboardOut(
        deals_today=deals_today,
        candidates_today=candidates_today,
        reply_required_open=reply_required_open,
        open_deal_count=open_deal_count,
        open_candidate_count=open_candidate_count,
        top_companies=[{"name": name, "deal_count": count} for name, count in top_companies_rows],
        reply_rate=insights.reply_rate,
        avg_reply_speed_hours=insights.avg_reply_speed_hours,
        deal_win_rate=insights.deal_win_rate,
        weekly_contact_frequency=insights.weekly_contact_frequency,
    )


class OverdueReplyOut(BaseModel):
    message_id: str
    subject: str
    sender_address: str
    received_at: datetime
    hours_overdue: float


class UpcomingMeetingOut(BaseModel):
    id: str
    title: str
    platform: str
    starts_at: datetime
    source_message_id: str | None = None


class ExpiringDealOut(BaseModel):
    id: str
    title: str
    reply_deadline: str
    days_overdue: int
    source_message_id: str | None = None


class RecommendedActionOut(BaseModel):
    kind: str
    label: str
    ref_id: str
    urgency_score: float
    message_id: str | None = None


class RemindersOut(BaseModel):
    overdue_replies: list[OverdueReplyOut]
    upcoming_meetings: list[UpcomingMeetingOut]
    expiring_deals: list[ExpiringDealOut]
    recommended_actions: list[RecommendedActionOut]


@router.get("/reminders", response_model=RemindersOut)
def get_reminders(db: Session = Depends(get_db)) -> RemindersOut:
    """返信忘れ・会議予定・期限切れ案件 + AIおすすめ対応順 — separate from the
    main dashboard payload so it can be polled/refreshed independently and
    stays easy to test in isolation."""
    reminders = compute_reminders(db)
    return RemindersOut(
        overdue_replies=[OverdueReplyOut(**vars(r)) for r in reminders.overdue_replies],
        upcoming_meetings=[UpcomingMeetingOut(**vars(m)) for m in reminders.upcoming_meetings],
        expiring_deals=[ExpiringDealOut(**vars(d)) for d in reminders.expiring_deals],
        recommended_actions=[RecommendedActionOut(**vars(a)) for a in reminders.recommended_actions],
    )
