"""3行 / 10行 / 詳細 summary levels, stored together on AIAnalysis so the UI
can switch between them instantly without a re-request."""
from __future__ import annotations

from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import mask_text
from app.db.models.ai import AIAnalysis
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.registry import get_llm_provider

SummaryLevel = Literal["3line", "10line", "detailed"]

_LEVEL_INSTRUCTIONS: dict[SummaryLevel, str] = {
    "3line": "このメールを日本語で3行以内に要約してください。",
    "10line": "このメールを日本語で10行以内、箇条書き中心で要約してください。",
    "detailed": "このメールの内容を日本語で詳細に要約してください。背景・要求事項・期限・次のアクションを含めてください。",
}


async def summarize_message(db: Session, message: Message, level: SummaryLevel) -> str:
    settings = get_settings()
    body = mask_text(message.body_text) if settings.anonymize_before_send else message.body_text
    system_prompt = "あなたはSES営業メールの要約アシスタントです。" + _LEVEL_INSTRUCTIONS[level]
    user_prompt = f"件名: {message.subject}\n本文:\n{body}"

    provider = get_llm_provider()
    try:
        response = await provider.complete_text(system_prompt=system_prompt, user_prompt=user_prompt)
        text = response.text
    except LLMProviderError:
        text = (message.body_text or "")[:120] + "…" if level != "detailed" else (message.body_text or "")

    analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
    if analysis is None:
        analysis = AIAnalysis(message_id=message.id, provider_used=provider.name)
        db.add(analysis)

    field_name = {"3line": "summary_3line", "10line": "summary_10line", "detailed": "summary_detailed"}[level]
    setattr(analysis, field_name, text)
    db.commit()
    return text
