"""AI返信支援: generates a reply draft for one of the fixed tones the spec
lists (丁寧/普通/営業/フレンドリー/断る/日程調整/お礼/催促/確認/謝罪).

`style_hint` is optional free text distilled from the user's own past
sent-mail corpus (Phase 2: a small few-shot sample of the user's previous
replies) so drafts drift toward their voice; omitted here since building
that corpus requires the mail-sync pipeline this scaffold stubs out.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import mask_text
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.registry import get_llm_provider

TONES = ["丁寧", "普通", "営業", "フレンドリー", "断る", "日程調整", "お礼", "催促", "確認", "謝罪"]


async def suggest_reply(db: Session, message: Message, tone: str, *, style_hint: str = "") -> str:
    if tone not in TONES:
        raise ValueError(f"unknown tone {tone!r}, expected one of {TONES}")

    settings = get_settings()
    body = mask_text(message.body_text) if settings.anonymize_before_send else message.body_text

    system_prompt = (
        f"あなたはSES営業担当者の代わりにメール返信を下書きするアシスタントです。"
        f"トーンは『{tone}』にしてください。"
        + (f" 過去のメール文体の特徴: {style_hint}" if style_hint else "")
    )
    user_prompt = f"元のメール件名: {message.subject}\n元のメール本文:\n{body}\n\n上記への返信メール本文を作成してください。"

    provider = get_llm_provider()
    try:
        response = await provider.complete_text(system_prompt=system_prompt, user_prompt=user_prompt)
        return response.text
    except LLMProviderError:
        return (
            f"[{tone}な返信の下書きを生成できませんでした。AIプロバイダーが利用できません]\n\n"
            f"{message.sender_name} 様\n\nお世話になっております。\n\n（本文をここに記入してください）\n\nよろしくお願いいたします。"
        )
