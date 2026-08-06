"""Chronological interaction history for a Contact ("今までにこんなやり取り
があったか見える" — the AI panel only ever showed data for the single
currently-open message, never a contact's full history), plus an
on-demand relationship summary. The summary is a manual POST-triggered
call, never run automatically, consistent with this app's token-cost
discipline (see analysis_service's module docstring): building the
timeline itself is pure DB reads, no LLM call.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.ai import AIAnalysis
from app.db.models.company import Contact
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.registry import get_llm_provider

# Only the last N entries go into the summary prompt — a contact with years
# of history shouldn't balloon the token count for what's meant to be a
# quick "what's the state of this relationship" glance.
_SUMMARY_MAX_ENTRIES = 15


@dataclass
class TimelineEntry:
    message_id: str
    subject: str
    direction: str  # "inbound" | "outbound"
    folder: str
    received_at: datetime | None
    summary: str | None
    top_category: str | None


def _addresses(raw: str) -> list[str]:
    try:
        return json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return []


def build_timeline(db: Session, contact: Contact) -> list[TimelineEntry]:
    if not contact.email_address:
        return []

    inbound = db.query(Message).filter(Message.sender_address == contact.email_address).all()
    sent_candidates = db.query(Message).filter(Message.folder == "Sent").all()
    outbound = [m for m in sent_candidates if contact.email_address in _addresses(m.to_addresses)]

    analyses = {
        a.message_id: a
        for a in db.query(AIAnalysis).filter(AIAnalysis.message_id.in_([m.id for m in inbound + outbound])).all()
    }

    entries: list[TimelineEntry] = []
    for message, direction in [(m, "inbound") for m in inbound] + [(m, "outbound") for m in outbound]:
        analysis = analyses.get(message.id)
        summary = analysis.summary_3line if analysis and analysis.summary_3line else None
        top_category = None
        if analysis and analysis.classification_json:
            try:
                top_category = json.loads(analysis.classification_json).get("mail_type")
            except json.JSONDecodeError:
                top_category = None
        entries.append(
            TimelineEntry(
                message_id=message.id,
                subject=message.subject,
                direction=direction,
                folder=message.folder,
                received_at=message.received_at,
                summary=summary,
                top_category=top_category,
            )
        )

    entries.sort(key=lambda e: e.received_at or datetime.min)
    return entries


async def summarize_relationship(contact: Contact, entries: list[TimelineEntry]) -> str:
    if not entries:
        return "まだやり取りの記録がありません。"

    recent = entries[-_SUMMARY_MAX_ENTRIES:]
    lines = [
        f"[{'受信' if e.direction == 'inbound' else '送信'}] "
        f"{e.received_at.strftime('%Y-%m-%d') if e.received_at else '日付不明'} 件名: {e.subject}"
        + (f" / 種別: {e.top_category}" if e.top_category else "")
        for e in recent
    ]
    system_prompt = (
        "あなたはSES営業アシスタントです。ある連絡先との過去のメールのやり取り一覧（件名・日付・分類のみ）が"
        "与えられます。これまでの関係性、やり取りの傾向、直近の状況を日本語で3〜5行に要約してください。"
    )
    user_prompt = "\n".join(lines)

    provider = get_llm_provider()
    try:
        response = await provider.complete_text(system_prompt=system_prompt, user_prompt=user_prompt)
        return response.text
    except LLMProviderError:
        return f"（{contact.name or contact.email_address}との過去{len(entries)}件のやり取りを自動要約できませんでした。AIプロバイダーの設定を確認してください。）"
