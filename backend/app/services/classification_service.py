"""Runs the "AI分類プロンプト" task for a Message and persists an AIAnalysis
row. This is the module that implements the non-functional requirement
"AI機能を無効化しても通常のメーラーとして利用できる" / "API障害時でも通常の
メーラーとして使用可能": any LLMProviderError from the configured provider
is caught and we retry once against LocalMockProvider, tagging the result
`is_fallback=True` so the UI can show "オフライン分類" instead of pretending
it's a full AI result.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import content_hash, mask_text
from app.db.models.ai import AIAnalysis, AuditLogEntry
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.local_mock import LocalMockProvider
from app.providers.llm.registry import get_llm_provider
from app.schemas.classification import ClassificationResult

DEFAULT_SYSTEM_PROMPT = (
    "あなたはSES営業向けメールアシスタントです。営業メール全体を解析し、"
    "単純な『案件か人材か』ではなく、優先度・返信要否・期限・アクション・"
    "営業フェーズ・重要ワード・危険ワード・営業機会・ネガティブ要素・緊急度・"
    "感情・温度感まで含めて判定し、指定されたJSONスキーマで返答してください。"
    "未知のカテゴリが妥当な場合は、既存の分類に加えて自由に追加してください。"
)


@dataclass
class ClassificationOutcome:
    analysis: AIAnalysis
    result: ClassificationResult
    from_cache: bool


def _build_user_prompt(message: Message, *, anonymize: bool) -> str:
    body = message.body_text or ""
    if anonymize:
        body = mask_text(body)
    parts = [
        f"件名: {message.subject}",
        f"送信元: {message.sender_name} <{message.sender_address}>",
        f"CC: {message.cc_addresses}",
        f"署名: {message.signature_text}",
        f"添付ファイル名: {', '.join(a.file_name for a in message.attachments)}",
        "本文:",
        body,
    ]
    for attachment in message.attachments:
        if not attachment.extracted_text:
            continue
        snippet = attachment.extracted_text[:1500]
        if anonymize:
            snippet = mask_text(snippet)
        parts.append(f"\n添付ファイル「{attachment.file_name}」({attachment.classified_kind or '種別不明'})の抜粋:\n{snippet}")
    return "\n".join(parts)


async def classify_message(db: Session, message: Message, *, force: bool = False) -> ClassificationOutcome:
    settings = get_settings()
    hash_input = content_hash(
        message.subject,
        message.body_text,
        ",".join(sorted(a.file_name for a in message.attachments)),
    )

    existing = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
    if existing and existing.content_hash == hash_input and not force:
        return ClassificationOutcome(
            analysis=existing,
            result=ClassificationResult.model_validate(json.loads(existing.classification_json)),
            from_cache=True,
        )

    user_prompt = _build_user_prompt(message, anonymize=settings.anonymize_before_send)
    provider = get_llm_provider()
    is_fallback = False

    try:
        raw, _usage = await provider.complete_json(system_prompt=DEFAULT_SYSTEM_PROMPT, user_prompt=user_prompt)
    except LLMProviderError:
        provider = LocalMockProvider()
        is_fallback = True
        raw, _usage = await provider.complete_json(system_prompt=DEFAULT_SYSTEM_PROMPT, user_prompt=user_prompt)

    result = ClassificationResult.model_validate(raw)

    if existing:
        analysis = existing
    else:
        analysis = AIAnalysis(message_id=message.id)
        db.add(analysis)

    analysis.content_hash = hash_input
    analysis.provider_used = provider.name
    analysis.classification_json = json.dumps(result.model_dump(), ensure_ascii=False)
    analysis.is_fallback = is_fallback
    db.flush()

    db.add(
        AuditLogEntry(
            message_id=message.id,
            action="classify",
            provider_used=provider.name,
            rationale=result.rationale or "根拠は返却されませんでした。",
            data_sent_summary="件名/送信元/CC/署名/添付ファイル名/本文" + ("（匿名化済み）" if settings.anonymize_before_send else ""),
            anonymized=settings.anonymize_before_send,
        )
    )
    db.commit()

    return ClassificationOutcome(analysis=analysis, result=result, from_cache=False)
