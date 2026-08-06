"""Runs the "AI分類プロンプト" task for a Message and persists an AIAnalysis
row. This is the module that implements the non-functional requirement
"AI機能を無効化しても通常のメーラーとして利用できる" / "API障害時でも通常の
メーラーとして使用可能": any LLMProviderError from the configured provider
is caught and we retry once against LocalMockProvider, tagging the result
`is_fallback=True` so the UI can show "オフライン分類" instead of pretending
it's a full AI result.

A real provider returning syntactically valid JSON that doesn't match
ClassificationResult's shape (missing required `mail_type`, wrong type for
a field, etc. — response_format=json_object only guarantees valid JSON,
not a matching schema) is just as much a "the AI didn't give us something
usable" case as a network error, so pydantic's ValidationError is caught
alongside LLMProviderError and triggers the same offline fallback instead
of bubbling up as an unhandled 500 (which is what "AI分類に失敗しました"
in the UI used to mean before this fix).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import content_hash, mask_text
from app.db.models.ai import AIAnalysis, AuditLogEntry
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.local_mock import LocalMockProvider
from app.providers.llm.registry import get_llm_provider
from app.schemas.classification import ClassificationResult
from app.services.feedback_service import build_few_shot_suffix, get_similar_corrections
from app.services.prompt_service import get_active_prompt, render_template, truncate_for_ai

TASK = "classification"

DEFAULT_SYSTEM_PROMPT = (
    "あなたはSES営業向けメールアシスタントです。営業メール全体を解析し、"
    "単純な『案件か人材か』ではなく、優先度・返信要否・期限・アクション・"
    "営業フェーズ・重要ワード・危険ワード・営業機会・ネガティブ要素・緊急度・"
    "感情・温度感まで含めて判定し、指定されたJSONスキーマで返答してください。"
    "未知のカテゴリが妥当な場合は、既存の分類に加えて自由に追加してください。\n\n"
    "【案件紹介 と 人材紹介 の判別基準】\n"
    "添付ファイルがスキルシート・経歴書・職務経歴書である、または本文に"
    "特定の技術者個人のスキル・経験・稼働状況が記載されている場合は、"
    "その技術者を紹介するメールなので『人材紹介』としてください"
    "（案件の詳細も併記されていても、主題が技術者個人の紹介であれば人材紹介です）。"
    "逆に、募集中の案件（業務内容・単価・勤務地・商流など）を紹介し、"
    "技術者個人の情報を伴わない場合は『案件紹介』としてください。\n\n"
    "【reply_required（返信要否）の判定基準】\n"
    "送信者が明確に返答・確認・日程回答・可否連絡を求めている場合、"
    "または期限付きで反応を求めている場合は true にしてください。"
    "単なる情報共有・広告配信・システム通知・お礼メール・完了報告など、"
    "こちらからの返信が本質的に不要なものは false としてください。"
)

DEFAULT_USER_PROMPT_TEMPLATE = (
    "件名: {{ subject }}\n"
    "送信元: {{ sender_name }} <{{ sender_address }}>\n"
    "CC: {{ cc_addresses }}\n"
    "署名: {{ signature_text }}\n"
    "添付ファイル名: {{ attachment_names }}\n"
    "本文:\n{{ body }}{{ attachment_excerpts }}"
)


@dataclass
class ClassificationOutcome:
    analysis: AIAnalysis
    result: ClassificationResult
    from_cache: bool


def build_context(message: Message, *, anonymize: bool) -> dict[str, str]:
    """Shared by classification_service and analysis_service (the combined
    classify+extract call) so both send an identically-truncated body —
    see Settings.max_body_chars_for_ai / max_attachment_excerpt_chars."""
    settings = get_settings()
    body = message.body_text or ""
    if anonymize:
        body = mask_text(body)
    body = truncate_for_ai(body, settings.max_body_chars_for_ai)

    excerpts = []
    for attachment in message.attachments:
        if not attachment.extracted_text:
            continue
        snippet = truncate_for_ai(attachment.extracted_text, settings.max_attachment_excerpt_chars)
        if anonymize:
            snippet = mask_text(snippet)
        excerpts.append(f"\n添付ファイル「{attachment.file_name}」({attachment.classified_kind or '種別不明'})の抜粋:\n{snippet}")

    return {
        "subject": message.subject,
        "sender_name": message.sender_name,
        "sender_address": message.sender_address,
        "cc_addresses": message.cc_addresses,
        "signature_text": message.signature_text,
        "attachment_names": ", ".join(a.file_name for a in message.attachments),
        "body": body,
        "attachment_excerpts": "".join(excerpts),
    }


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

    active_prompt = get_active_prompt(db, TASK)
    system_prompt = active_prompt.system_prompt if active_prompt else DEFAULT_SYSTEM_PROMPT
    user_template = active_prompt.user_prompt_template if active_prompt else DEFAULT_USER_PROMPT_TEMPLATE
    context = build_context(message, anonymize=settings.anonymize_before_send)
    user_prompt = render_template(user_template, context)
    user_prompt += build_few_shot_suffix(await get_similar_corrections(db, message))

    provider = get_llm_provider()
    is_fallback = False

    try:
        raw, _usage = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        result = ClassificationResult.model_validate(raw)
    except (LLMProviderError, ValidationError):
        provider = LocalMockProvider()
        is_fallback = True
        raw, _usage = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        result = ClassificationResult.model_validate(raw)

    if existing:
        analysis = existing
    else:
        analysis = AIAnalysis(message_id=message.id)
        db.add(analysis)

    analysis.content_hash = hash_input
    analysis.provider_used = provider.name
    analysis.prompt_template_id = active_prompt.template_id if active_prompt else None
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
