"""営業インサイト: reply rate, response speed, deal win rate, contact
frequency — DESIGN.md's "商品化を見据えて追加すると差別化しやすい機能"
differentiator list.

Pure DB aggregation, no LLM calls (keeps it free to compute and safe to
refresh on every dashboard load). Depends on the thread grouping and
sent-mail persistence added alongside this module (see
services/mail/threading_service.py and mail.py's send_reply) — without
those, "reply rate" and "response speed" have no data to work from at all.

Definitions are necessarily approximate given what's actually tracked:
- reply_rate: of threads that contain at least one inbound message, what
  fraction also contain at least one message in the "Sent" folder.
- avg_reply_speed_hours: for threads that were replied to, average time
  from the first inbound message to the first Sent message after it.
- deal_win_rate: filled / (filled + closed), i.e. of *resolved* deals
  (excludes still-open ones), what fraction were won. None when there are
  no resolved deals yet, rather than a misleading 0.
- weekly_contact_frequency: total messages (any folder) in the last N
  weeks, divided by N.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models.ai import AIAnalysis
from app.db.models.deal import Deal
from app.db.models.email import Message
from app.db.models.meeting import Meeting


@dataclass
class InsightsSummary:
    reply_rate: float | None
    avg_reply_speed_hours: float | None
    deal_win_rate: float | None
    weekly_contact_frequency: float
    threads_with_inbound: int
    threads_replied: int


def compute_insights(db: Session, *, weeks_for_frequency: int = 8) -> InsightsSummary:
    messages = db.query(Message).filter(Message.thread_id.isnot(None)).all()

    threads: dict[str, list[Message]] = {}
    for message in messages:
        threads.setdefault(message.thread_id, []).append(message)

    threads_with_inbound = 0
    threads_replied = 0
    reply_speed_samples: list[float] = []

    for thread_messages in threads.values():
        inbound = [m for m in thread_messages if m.folder not in ("Sent", "Drafts")]
        sent = [m for m in thread_messages if m.folder == "Sent"]
        if not inbound:
            continue
        threads_with_inbound += 1
        if not sent:
            continue
        threads_replied += 1

        first_inbound = min((m for m in inbound if m.received_at), key=lambda m: m.received_at, default=None)
        if first_inbound is None:
            continue
        replies_after = [m for m in sent if m.received_at and m.received_at >= first_inbound.received_at]
        if not replies_after:
            continue
        first_reply = min(replies_after, key=lambda m: m.received_at)
        delta_hours = (first_reply.received_at - first_inbound.received_at).total_seconds() / 3600
        if delta_hours >= 0:
            reply_speed_samples.append(delta_hours)

    reply_rate = threads_replied / threads_with_inbound if threads_with_inbound else None
    avg_reply_speed_hours = sum(reply_speed_samples) / len(reply_speed_samples) if reply_speed_samples else None

    deals = db.query(Deal).all()
    filled = sum(1 for d in deals if d.status == "filled")
    closed = sum(1 for d in deals if d.status == "closed")
    deal_win_rate = filled / (filled + closed) if (filled + closed) > 0 else None

    window_start = datetime.utcnow() - timedelta(weeks=weeks_for_frequency)
    recent_count = db.query(Message).filter(Message.received_at >= window_start).count()
    weekly_contact_frequency = recent_count / weeks_for_frequency

    return InsightsSummary(
        reply_rate=reply_rate,
        avg_reply_speed_hours=avg_reply_speed_hours,
        deal_win_rate=deal_win_rate,
        weekly_contact_frequency=weekly_contact_frequency,
        threads_with_inbound=threads_with_inbound,
        threads_replied=threads_replied,
    )


@dataclass
class OverdueReply:
    message_id: str
    subject: str
    sender_address: str
    received_at: datetime
    hours_overdue: float


@dataclass
class UpcomingMeeting:
    id: str
    title: str
    platform: str
    starts_at: datetime


@dataclass
class ExpiringDeal:
    id: str
    title: str
    reply_deadline: str
    days_overdue: int


@dataclass
class RecommendedAction:
    kind: str  # "reply" | "deal" | "meeting"
    label: str
    ref_id: str
    urgency_score: float


@dataclass
class RemindersSummary:
    overdue_replies: list[OverdueReply]
    upcoming_meetings: list[UpcomingMeeting]
    expiring_deals: list[ExpiringDeal]
    recommended_actions: list[RecommendedAction]


def compute_reminders(
    db: Session, *, overdue_reply_hours: float = 24.0, upcoming_meeting_days: int = 7, limit: int = 10
) -> RemindersSummary:
    """返信忘れ・会議予定・期限切れ案件 + a merged "AIおすすめ対応順" list.

    The merge is a simple heuristic, not a learned ranking: every item's
    urgency_score is expressed in roughly-comparable "hours of urgency" so
    a moderately overdue reply and a meeting starting soon can be sorted
    together, not a claim of optimal prioritization.
    """
    now = datetime.utcnow()

    inbound_messages = db.query(Message).filter(Message.folder.notin_(["Sent", "Drafts"])).all()
    threads: dict[str, list[Message]] = {}
    for message in db.query(Message).filter(Message.thread_id.isnot(None)).all():
        threads.setdefault(message.thread_id, []).append(message)

    overdue_replies: list[OverdueReply] = []
    for message in inbound_messages:
        if not message.received_at:
            continue
        hours_since = (now - message.received_at).total_seconds() / 3600
        if hours_since < overdue_reply_hours:
            continue

        analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
        if not analysis or not analysis.classification_json:
            continue
        try:
            classification = json.loads(analysis.classification_json)
        except json.JSONDecodeError:
            continue
        if not classification.get("reply_required"):
            continue

        thread_messages = threads.get(message.thread_id, []) if message.thread_id else []
        already_replied = any(
            m.folder == "Sent" and m.received_at and m.received_at >= message.received_at for m in thread_messages
        )
        if already_replied:
            continue

        overdue_replies.append(
            OverdueReply(
                message_id=message.id,
                subject=message.subject,
                sender_address=message.sender_address,
                received_at=message.received_at,
                hours_overdue=hours_since - overdue_reply_hours,
            )
        )
    overdue_replies.sort(key=lambda r: r.hours_overdue, reverse=True)
    overdue_replies = overdue_replies[:limit]

    window_end = now + timedelta(days=upcoming_meeting_days)
    meetings = (
        db.query(Meeting)
        .filter(Meeting.starts_at.isnot(None), Meeting.starts_at >= now, Meeting.starts_at <= window_end)
        .order_by(Meeting.starts_at.asc())
        .limit(limit)
        .all()
    )
    upcoming_meetings = [
        UpcomingMeeting(id=m.id, title=m.title, platform=m.platform, starts_at=m.starts_at) for m in meetings
    ]

    today = now.date()
    open_deals = (
        db.query(Deal).filter(Deal.status == "open", Deal.reply_deadline.isnot(None), Deal.reply_deadline < today).all()
    )
    expiring_deals = [
        ExpiringDeal(
            id=d.id, title=d.title, reply_deadline=d.reply_deadline.isoformat(), days_overdue=(today - d.reply_deadline).days
        )
        for d in open_deals
    ]
    expiring_deals.sort(key=lambda d: d.days_overdue, reverse=True)
    expiring_deals = expiring_deals[:limit]

    recommended: list[RecommendedAction] = []
    for r in overdue_replies:
        recommended.append(
            RecommendedAction(kind="reply", label=f"「{r.subject}」への返信", ref_id=r.message_id, urgency_score=r.hours_overdue)
        )
    for d in expiring_deals:
        recommended.append(
            RecommendedAction(kind="deal", label=f"案件「{d.title}」の返信期限切れ", ref_id=d.id, urgency_score=d.days_overdue * 24)
        )
    for m in upcoming_meetings:
        hours_until = (m.starts_at - now).total_seconds() / 3600
        recommended.append(
            RecommendedAction(
                kind="meeting",
                label=f"会議「{m.title}」",
                ref_id=m.id,
                urgency_score=max(0.0, upcoming_meeting_days * 24 - hours_until),
            )
        )
    recommended.sort(key=lambda a: a.urgency_score, reverse=True)
    recommended = recommended[:limit]

    return RemindersSummary(
        overdue_replies=overdue_replies,
        upcoming_meetings=upcoming_meetings,
        expiring_deals=expiring_deals,
        recommended_actions=recommended,
    )
