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

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models.deal import Deal
from app.db.models.email import Message


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
