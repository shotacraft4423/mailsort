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
        cached_extraction = ExtractionResult.model_validate(json.loads(existing.extraction_json or "{}"))
        # Folder routing / meeting extraction / contact upsert used to only
        # run on the fresh-analysis path below. Every message that had
        # already been classified before those features existed (or before
        # auto-routing was turned on) would then hit this cache branch on
        # every later re-classify and never get routed/upserted at all —
        # "全部分類したのにフォルダ分けされない" — even though re-running
        # rules/plugins on a cache hit was already correct. Cache hits now
        # get exactly the same side effects a fresh analysis does.
        _apply_post_analysis_side_effects(db, message, cached_classification, cached_extraction, settings)
        await _run_rules_and_plugins_safely(db, message, existing, cached_classification)
        return AnalysisOutcome(
            analysis=existing,
            classification=cached_classification,
            extraction=cached_extraction,
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

    # Populates Company/Contact so the AI panel's 会社情報 tab and the
    # contacts list have anything to show at all — this existed as a
    # standalone function with a docstring claiming it ran "after
    # extraction_service.extract_message succeeds" but nothing in the app
    # actually called it, so every company/contact tab stayed empty.
    _apply_post_analysis_side_effects(db, message, classification, extraction, settings)
    await _run_rules_and_plugins_safely(db, message, analysis, classification)

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

# A message currently sitting in one of the heuristic's own possible
# destinations (including "要返信", which isn't in the map above since
# it's driven by reply_required rather than a category) is fair game to
# re-route — otherwise a message auto-filed under the wrong category on
# an earlier pass (e.g. the model's top category differed then, or an
# older build of this heuristic decided differently) stayed wrong
# forever: re-classifying only ever routed messages still sitting in
# INBOX, and this heuristic is exactly what put it in the "wrong" folder
# in the first place. A message anywhere else (Archive/Trash/Sent/Drafts,
# or a custom folder a rule or the user filed it into) is left alone.
_AUTO_ROUTABLE_FOLDERS = {"INBOX", "要返信", *_CATEGORY_FOLDER_MAP.values()}

# "基本的にスキルシートが添付、もしくは人間のスキルが本文に書いてあるものは
# 案件ではなく人材です" — a real user-reported misroute (a message with a
# skill-sheet spreadsheet attachment landed in 案件 because the model's
# category scores came back tied). Whether an attachment is a skill sheet /
# resume is something attachment_analysis_service already determines
# deterministically (keyword match against the file name/content, see
# AttachmentKind), so this is a zero-token, zero-ambiguity override rather
# than something worth re-asking the LLM about on every re-classify.
_CANDIDATE_ATTACHMENT_KINDS = {"skill_sheet", "resume"}


def _apply_post_analysis_side_effects(
    db: Session,
    message: Message,
    classification: ClassificationResult,
    extraction: ExtractionResult,
    settings: Settings,
) -> None:
    """Meeting extraction / folder routing / contact upsert are secondary
    side effects of a classification, not what the caller (the "AI分類を
    実行" button, bulk-classify, the sync queue) actually asked for and is
    waiting on. A bug in any one of them — e.g. company_aggregation_
    service raising MultipleResultsFound the first time it ever ran at
    scale against real (messy, duplicate-prone) mail data — used to crash
    the entire /ai/messages/{id}/analyze call, turning every message that
    hit it into a hard failure with no classification result at all. Each
    step is isolated so one failing skips only that step; db.rollback()
    clears the session's pending-rollback state a caught exception leaves
    behind, since otherwise the *next* step's first query would also fail
    with PendingRollbackError even though it has nothing to do with the
    original error."""
    for step in (
        lambda: _extract_meetings_once(db, message, extraction),
        lambda: _route_to_category_folder(db, message, classification, settings),
        lambda: company_aggregation_service.upsert_company_and_contact(db, message, extraction),
    ):
        try:
            step()
        except Exception:  # noqa: BLE001 - best-effort side effect, must never fail the caller
            db.rollback()


async def _run_rules_and_plugins_safely(
    db: Session, message: Message, analysis: AIAnalysis, classification: ClassificationResult
) -> None:
    try:
        await _run_rules_and_plugins(db, message, analysis, classification)
    except Exception:  # noqa: BLE001 - same rationale as _apply_post_analysis_side_effects
        db.rollback()


def _route_to_category_folder(db: Session, message: Message, classification: ClassificationResult, settings: Settings) -> None:
    """"せっかく分類したんだからその分類ごとにフォルダへの振り分けが欲しい" —
    classification previously only ever produced tags/badges the user had
    to go looking for; nothing moved the message anywhere. Only touches
    messages sitting in INBOX or one of this heuristic's own destination
    folders, so it can correct its own past decisions but never yanks
    something out of a folder the user (or a rule) filed it into on
    purpose (Archive/Trash/Sent/Drafts/a custom rule folder)."""
    if not settings.auto_route_by_classification or message.folder not in _AUTO_ROUTABLE_FOLDERS:
        return

    target = _CATEGORY_FOLDER_MAP.get(classification.top_category())
    if any(a.classified_kind in _CANDIDATE_ATTACHMENT_KINDS for a in message.attachments):
        target = "人材"
    if target is None and classification.reply_required:
        target = "要返信"
    if target and target != message.folder:
        message.folder = target
        db.commit()


def reroute_classified_messages(db: Session) -> int:
    """"すでに割り振られてしまったメールの再振り分けを行えるようにして" —
    _route_to_category_folder only ever runs as a side effect of
    analyze_message, and nothing re-invokes analyze_message for a message
    that's already been classified unless someone opens it and clicks
    再分類, or a bulk-classify happens to cover it — but bulk-classify only
    ever reads whatever folder the user is currently viewing, and a message
    that was misfiled by an earlier, buggier version of this heuristic is
    (by definition) not sitting in the folder someone would think to
    bulk-classify. This sweeps every already-analyzed message directly from
    its cached classification, independent of which folder each one is
    currently in, so it costs zero LLM calls and can be run on demand
    across the whole mailbox to clean up past misrouting."""
    settings = get_settings()
    if not settings.auto_route_by_classification:
        return 0

    candidates = (
        db.query(Message, AIAnalysis)
        .join(AIAnalysis, AIAnalysis.message_id == Message.id)
        .filter(Message.folder.in_(_AUTO_ROUTABLE_FOLDERS))
        .all()
    )

    moved = 0
    for message, analysis in candidates:
        classification = ClassificationResult.model_validate(json.loads(analysis.classification_json or "{}"))
        previous_folder = message.folder
        _route_to_category_folder(db, message, classification, settings)
        if message.folder != previous_folder:
            moved += 1
    return moved


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
