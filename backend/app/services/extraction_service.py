"""Runs the "AI抽出" task, populating AIAnalysis.extraction_json. Shares the
same cache-by-content-hash / offline-fallback pattern as
classification_service.py (see that module's docstring for why pydantic's
ValidationError — a real provider's JSON not matching ExtractionResult's
field types — is caught alongside LLMProviderError instead of crashing the
request).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import content_hash, mask_text
from app.db.models.ai import AIAnalysis
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.local_mock import LocalMockProvider
from app.providers.llm.registry import get_llm_provider
from app.schemas.extraction import ExtractionResult
from app.services.ai_schema_normalization import normalize_for_schema
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


# Round 4 of the real AI-JSON-shape-drift bug class (see
# ai_schema_normalization's module docstring for the full rule set/history):
# tool_links is a single nested ToolLinks object, but the model sometimes
# flattens it into a bare list of URL strings —
# ['https://gy53.asp.cuenote.jp/...'] or [] — instead of {"other_urls": [...]}.
# Rather than dump every stray URL into other_urls (which would silently
# break meeting_extraction_service's extraction.tool_links.teams/meet/zoom
# lookups), bucket each URL by domain the same way a properly-shaped
# response would have. This is registered as normalize_for_schema's
# bucketizer for the tool_links field — everything else on ExtractionResult
# (round 5's candidate_name/unit_price/location/period getting list[str],
# and attachments_mentioned/todo/questions/unanswered_items getting null) is
# handled generically by normalize_for_schema itself, purely from each
# field's type annotation.
_TOOL_LINK_DOMAIN_PATTERNS: tuple[tuple[str, str], ...] = (
    ("teams.microsoft.com", "teams"),
    ("zoom.us", "zoom"),
    ("meet.google.com", "meet"),
    ("chatwork.com", "chatwork"),
    ("slack.com", "slack"),
    ("backlog.com", "backlog"),
    ("backlog.jp", "backlog"),
    ("notion.so", "notion"),
    ("notion.site", "notion"),
    ("github.com", "github"),
    ("atlassian.net", "jira"),
    ("redmine", "redmine"),
)


def _categorize_tool_link(url: str) -> str:
    for domain, field in _TOOL_LINK_DOMAIN_PATTERNS:
        if domain in url:
            return field
    return "other_urls"


def _bucket_tool_links(urls: list) -> dict:
    buckets: dict[str, list[str]] = {}
    for url in urls:
        if not isinstance(url, str):
            continue
        buckets.setdefault(_categorize_tool_link(url), []).append(url)
    return buckets


# meeting is a single nested MeetingInfo object, but the model sometimes
# sends the whole thing as a bare date/time string instead — e.g.
# "8/4(火) 17:00～18:00＠web" instead of {"datetime_text": "8/4(火) ..."}.
# There's no participants/url/platform to recover from free text like this,
# so the whole string becomes datetime_text (meeting_extraction_service and
# the calendar view both already treat that field as raw, unparsed text).
def _bucket_meeting(texts: list) -> dict:
    joined = "; ".join(str(t) for t in texts if isinstance(t, str))
    return {"datetime_text": joined} if joined else {}


def normalize_extraction_payload(raw: dict) -> dict:
    return normalize_for_schema(
        ExtractionResult,
        raw,
        nested_object_bucketizers={"tool_links": _bucket_tool_links, "meeting": _bucket_meeting},
    )


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
        result = ExtractionResult.model_validate(normalize_extraction_payload(raw))
    except (LLMProviderError, ValidationError):
        # local mock has no dedicated extraction logic; empty result is a
        # safe default whether the provider failed outright or just
        # returned JSON that doesn't match ExtractionResult's shape.
        is_fallback = True
        result = ExtractionResult.model_validate({})

    analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
    if analysis is None:
        # content_hash is NOT NULL on AIAnalysis; this used to be left
        # unset here (extract_message is the only one of the three AI
        # services that creates AIAnalysis rows) and crashed with a
        # sqlite IntegrityError the moment this ran for a message with no
        # prior classify/analyze call.
        hash_input = content_hash(
            message.subject,
            message.body_text,
            ",".join(sorted(a.file_name for a in message.attachments)),
        )
        analysis = AIAnalysis(message_id=message.id, provider_used=provider.name, content_hash=hash_input)
        db.add(analysis)
    analysis.extraction_json = json.dumps(result.model_dump(), ensure_ascii=False)
    db.commit()

    return ExtractionOutcome(result=result, is_fallback=is_fallback)
