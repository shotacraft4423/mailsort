"""Combined classification+extraction in a single LLM call.

Token-efficiency note: the automatic per-message pipeline (queue.py, fired
on every synced email) used to make two separate LLM calls — one via
classification_service, one via extraction_service — each re-sending the
full email body plus its own system prompt. Since both tasks read the same
email and only differ in what JSON shape they ask for, merging them sends
the body once instead of twice and pays for one system prompt's overhead
instead of two. That roughly halves per-message input tokens on the
highest-volume path, which matters directly on a metered/low-tier plan.

Manual, single-purpose re-runs (the UI's per-task buttons, or testing one
prompt in isolation via the prompt editor) still go through
classification_service.classify_message / extraction_service.extract_message
individually — this module builds on top of them rather than replacing them.

Real-provider robustness: response_format=json_object only guarantees
syntactically valid JSON, not that it nests into the exact
{"classification": {...}, "extraction": {...}} shape this module asks for.
A real model omitting a required field (ClassificationResult.mail_type) or
using a wrong type raises pydantic's ValidationError, which is caught
alongside LLMProviderError and falls back to LocalMockProvider the same
way a network failure does — otherwise it surfaced as an unhandled 500
("AI分類に失敗しました" with zero explanation of why).
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import content_hash
from app.db.models.ai import AIAnalysis, AuditLogEntry
from app.db.models.email import Message
from app.db.models.meeting import Meeting
from app.providers.llm.base import LLMProviderError
from app.providers.llm.local_mock import LocalMockProvider
from app.providers.llm.registry import get_llm_provider
from app.schemas.classification import ClassificationResult
from app.schemas.extraction import ExtractionResult
from app.services import (
    classification_service,
    company_aggregation_service,
    extraction_service,
    meeting_extraction_service,
    plugin_manager,
    rule_engine,
)
from app.services.feedback_service import build_few_shot_suffix, get_similar_corrections
from app.services.prompt_service import get_active_prompt, render_template

# Matched by LocalMockProvider to return a combined stub shape instead of
# the plain classification shape — see providers/llm/local_mock.py.
COMBINED_MARKER = "統合解析タスク"


@dataclass
class AnalysisOutcome:
    analysis: AIAnalysis
    classification: ClassificationResult
    extraction: ExtractionResult
    from_cache: bool
    is_fallback: bool


def _combined_system_prompt(db: Session) -> tuple[str, str | None]:
    """Builds one system prompt out of whichever classification/extraction
    prompts are currently active (GUI-edited or module defaults), and
    returns the classification template's id for AIAnalysis.prompt_template_id
    bookkeeping (the extraction half doesn't get its own FK slot — see
    AIAnalysis.prompt_template_id's single-column design)."""
    active_classification = get_active_prompt(db, classification_service.TASK)
    active_extraction = get_active_prompt(db, extraction_service.TASK)

    classification_prompt = active_classification.system_prompt if active_classification else classification_service.DEFAULT_SYSTEM_PROMPT
    extraction_prompt = active_extraction.system_prompt if active_extraction else extraction_service.DEFAULT_SYSTEM_PROMPT

    system_prompt = (
        f"{COMBINED_MARKER}: 以下の2つのタスクを1回の応答でまとめて行ってください。\n\n"
        f"【タスク1: 分類】{classification_prompt}\n\n"
        f"【タスク2: 抽出】{extraction_prompt}\n\n"
        '必ず {"classification": {タスク1のJSONスキーマ}, "extraction": {タスク2のJSONスキーマ}} '
        "という単一のJSONオブジェクトのみを返してください。他の文章は含めないでください。"
    )
    template_id = active_classification.template_id if active_classification else None
    return system_prompt, template_id


async def analyze_message(db: Session, message: Message, *, force: bool = False) -> AnalysisOutcome:
    settings = get_settings()
    hash_input = content_hash(
        message.subject,
        message.body_text,
        ",".join(sorted(a.file_name for a in message.attachments)),
    )

    existing = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
    if existing and existing.content_hash == hash_input and not force:
        cached_classification = ClassificationResult.model_validate(json.loads(existing.classification_json or "{}"))
        await _run_rules_and_plugins(db, message, existing, cached_classification)
        return AnalysisOutcome(
            analysis=existing,
            classification=cached_classification,
            extraction=ExtractionResult.model_validate(json.loads(existing.extraction_json or "{}")),
            from_cache=True,
            is_fallback=existing.is_fallback,
        )

    system_prompt, template_id = _combined_system_prompt(db)
    active_classification = get_active_prompt(db, classification_service.TASK)
    user_template = (
        active_classification.user_prompt_template if active_classification else classification_service.DEFAULT_USER_PROMPT_TEMPLATE
    )
    context = classification_service.build_context(message, anonymize=settings.anonymize_before_send)
    user_prompt = render_template(user_template, context)
    user_prompt += build_few_shot_suffix(await get_similar_corrections(db, message))

    provider = get_llm_provider()
    is_fallback = False
    try:
        raw, _usage = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        classification = ClassificationResult.model_validate(raw.get("classification") or {})
        extraction = ExtractionResult.model_validate(raw.get("extraction") or {})
    except (LLMProviderError, ValidationError):
        provider = LocalMockProvider()
        is_fallback = True
        raw, _usage = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        classification = ClassificationResult.model_validate(raw.get("classification") or {})
        extraction = ExtractionResult.model_validate(raw.get("extraction") or {})

    if existing:
        analysis = existing
    else:
        analysis = AIAnalysis(message_id=message.id)
        db.add(analysis)

    analysis.content_hash = hash_input
    analysis.provider_used = provider.name
    analysis.prompt_template_id = template_id
    analysis.classification_json = json.dumps(classification.model_dump(), ensure_ascii=False)
    analysis.extraction_json = json.dumps(extraction.model_dump(), ensure_ascii=False)
    analysis.is_fallback = is_fallback
    db.flush()

    db.add(
        AuditLogEntry(
            message_id=message.id,
            action="analyze",
            provider_used=provider.name,
            rationale=classification.rationale or "根拠は返却されませんでした。",
            data_sent_summary=(
                "件名/送信元/CC/署名/添付ファイル名/本文（分類・抽出を1回のAI呼び出しでまとめて実行）"
                + ("（匿名化済み）" if settings.anonymize_before_send else "")
            ),
            anonymized=settings.anonymize_before_send,
        )
    )
    db.commit()

    _extract_meetings_once(db, message, extraction)
    _route_to_category_folder(db, message, classification, settings)
    # Populates Company/Contact so the AI panel's 会社情報 tab and the
    # contacts list have anything to show at all — this existed as a
    # standalone function with a docstring claiming it ran "after
    # extraction_service.extract_message succeeds" but nothing in the app
    # actually called it, so every company/contact tab stayed empty.
    company_aggregation_service.upsert_company_and_contact(db, message, extraction)

    await _run_rules_and_plugins(db, message, analysis, classification)

    return AnalysisOutcome(
        analysis=analysis, classification=classification, extraction=extraction, from_cache=False, is_fallback=is_fallback
    )


# Only categories with an obvious, low-risk destination — leaves "その他"/
# unclassified/unmapped categories in INBOX rather than guessing. "案件"/
# "人材"/"重要"/"要返信"/"Junk" match FolderList's DEFAULT_FOLDERS on the
# frontend so a routed message is always visible in the sidebar even for
# an account whose real IMAP mailbox has none of these folders.
_CATEGORY_FOLDER_MAP = {
    "案件紹介": "案件",
    "案件返信": "案件",
    "人材紹介": "人材",
    "人材返信": "人材",
    "重要": "重要",
    "迷惑メール": "Junk",
}


def _route_to_category_folder(db: Session, message: Message, classification: ClassificationResult, settings: Settings) -> None:
    """"せっかく分類したんだからその分類ごとにフォルダへの振り分けが欲しい" —
    classification previously only ever produced tags/badges the user had
    to go looking for; nothing moved the message anywhere. Only touches
    messages still sitting in INBOX so it never yanks something out of a
    folder the user (or a rule) already filed it into on purpose."""
    if not settings.auto_route_by_classification or message.folder != "INBOX":
        return

    target = _CATEGORY_FOLDER_MAP.get(classification.top_category())
    if target is None and classification.reply_required:
        target = "要返信"
    if target:
        message.folder = target
        db.commit()


def _extract_meetings_once(db: Session, message: Message, extraction: ExtractionResult) -> None:
    """meeting_extraction_service.extract_meetings() existed (with a regex
    fallback specifically so meeting links are "never missed just because
    AI is off") but was never called from anywhere in the app — the
    meeting calendar/agenda view and the AI panel's meeting tab were always
    empty regardless of how many Teams/Zoom/Meet links a synced email
    actually contained. Guarded by an existence check since analyze_message
    can re-run for the same message (force=True), and extract_meetings
    itself has no per-message idempotency of its own."""
    already_extracted = db.query(Meeting).filter(Meeting.source_message_id == message.id).first() is not None
    if not already_extracted:
        meeting_extraction_service.extract_meetings(db, message, extraction)


async def _run_rules_and_plugins(
    db: Session, message: Message, analysis: AIAnalysis, classification: ClassificationResult
) -> None:
    """Rules and plugins were configurable via the GUI (/rules, /plugins)
    but nothing in the pipeline ever called evaluate_rules() or
    dispatch_message_classified() — they were persisted and silently
    ignored. This is the wiring that makes them actually fire on every
    classified message, cached or fresh."""
    fired = rule_engine.evaluate_rules(db, message, analysis)
    rule_engine.apply_actions(db, message, fired)

    # Plugin hooks are arbitrary third-party code (see plugins/sample_slack_
    # notifier, which does a blocking network call) — running them on the
    # event loop thread would stall every other in-flight request, so this
    # goes through a worker thread same as the blocking IMAP calls do.
    await asyncio.to_thread(
        plugin_manager.dispatch_message_classified,
        {"id": message.id, "subject": message.subject, "sender_address": message.sender_address},
        classification.model_dump(),
    )
