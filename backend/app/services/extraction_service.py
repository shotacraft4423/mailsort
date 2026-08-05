"""Runs the "AI抽出" task, populating AIAnalysis.extraction_json. Shares the
same cache-by-content-hash / offline-fallback pattern as
classification_service.py (see that module's docstring for the rationale).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import mask_text
from app.db.models.ai import AIAnalysis
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.local_mock import LocalMockProvider
from app.providers.llm.registry import get_llm_provider
from app.schemas.extraction import ExtractionResult
from app.services.prompt_service import get_active_prompt, render_template, truncate_for_ai

TASK = "extraction"

DEFAULT_SYSTEM_PROMPT = (
    "あなたはSES営業メールから構造化データを抽出するアシスタントです。"
    "会社名・担当者・電話番号・メール・案件名・人材名・単価・勤務地・スキル・"
    "期間・募集人数・商流・勤務形態・外国籍可否・年齢・面談回数・備考・期限・"
    "返信期限・会議情報（Teams/Meet/Zoom等のURL含む）・Chatwork/Slack/Backlog/"
    "Notion/GitHub/Jira/Redmineのリンク・電話・FAX・住所・請求番号・注文番号・"
    "ToDo・質問事項・返信内容・未回答項目を、指定JSONスキーマで抽出してください。"
    "本文に存在しない項目はnullまたは空配列にしてください。"
)

DEFAULT_USER_PROMPT_TEMPLATE = "件名: {{ subject }}\n本文:\n{{ body }}"


@dataclass
class ExtractionOutcome:
    result: ExtractionResult
    is_fallback: bool


async def extract_message(db: Session, message: Message) -> ExtractionOutcome:
    settings = get_settings()
    body = mask_text(message.body_text) if settings.anonymize_before_send else message.body_text
    body = truncate_for_ai(body, settings.max_body_chars_for_ai)

    active_prompt = get_active_prompt(db, TASK)
    system_prompt = active_prompt.system_prompt if active_prompt else DEFAULT_SYSTEM_PROMPT
    user_template = active_prompt.user_prompt_template if active_prompt else DEFAULT_USER_PROMPT_TEMPLATE
    user_prompt = render_template(user_template, {"subject": message.subject, "body": body})

    provider = get_llm_provider()
    is_fallback = False
    try:
        raw, _usage = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
    except LLMProviderError:
        raw, is_fallback = {}, True  # local mock has no dedicated extraction logic; empty result is safe default

    result = ExtractionResult.model_validate(raw)

    analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
    if analysis is None:
        analysis = AIAnalysis(message_id=message.id, provider_used=provider.name)
        db.add(analysis)
    analysis.extraction_json = json.dumps(result.model_dump(), ensure_ascii=False)
    db.commit()

    return ExtractionOutcome(result=result, is_fallback=is_fallback)
