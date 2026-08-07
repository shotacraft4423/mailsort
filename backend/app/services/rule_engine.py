"""No-code rule engine ("特定企業は必ず重要", "特定キーワードはSlack通知").

Rules run after AI classification and can add tags / raise priority / fire
plugin actions. Deterministic conditions (subject/sender/mail_type/...) read
from plain Message fields (plus AI-derived fields when present) and never
depend on AI being available, so rules keep working with AI disabled. The
one exception is the "ai_prompt" condition type ("振り分けルールにもプロン
プト使えるように") — free text describing a judgment call too fuzzy for
equals/contains/starts_with (e.g. "クレームや強い不満が書かれている"),
evaluated by asking the configured LLM a yes/no question. That one condition
type is unavailable (never matches) when AI is disabled or the provider call
fails — every other condition and every other rule keeps working normally.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.ai import AIAnalysis
from app.db.models.email import Message
from app.db.models.rule import Rule
from app.db.models.tag import MessageTag, Tag
from app.providers.llm.base import LLMProviderError
from app.providers.llm.registry import get_llm_provider
from app.services.prompt_service import truncate_for_ai

logger = logging.getLogger(__name__)

AI_PROMPT_FIELD = "ai_prompt"

_FIELD_GETTERS = {
    "subject": lambda m, a: m.subject,
    "sender_address": lambda m, a: m.sender_address,
    "sender_name": lambda m, a: m.sender_name,
    "body_text": lambda m, a: m.body_text,
    "mail_type": lambda m, a: (json.loads(a.classification_json).get("mail_type") if a else None),
    "priority": lambda m, a: (json.loads(a.classification_json).get("priority") if a else None),
}

_OPERATORS = {
    "equals": lambda value, target: value == target,
    "contains": lambda value, target: isinstance(value, str) and target in value,
    "starts_with": lambda value, target: isinstance(value, str) and value.startswith(target),
    "in": lambda value, target: value in target,
}

_AI_CONDITION_SYSTEM_PROMPT = (
    "あなたはメール振り分けルールの条件判定アシスタントです。"
    "与えられた「判定基準」に、このメールが当てはまるかどうかを判定し、"
    '必ず {"matches": true} または {"matches": false} という形式のJSONのみで回答してください。'
    "判定基準に迷う場合はfalseにしてください。"
)


@dataclass
class RuleFireResult:
    rule: Rule
    actions: list[dict[str, Any]]


def _evaluate_condition(condition: dict[str, Any], message: Message, analysis: AIAnalysis | None) -> bool:
    getter = _FIELD_GETTERS.get(condition["field"])
    operator = _OPERATORS.get(condition["operator"])
    if getter is None or operator is None:
        return False
    value = getter(message, analysis)
    if value is None:
        return False
    try:
        return bool(operator(value, condition["value"]))
    except TypeError:
        return False


def _condition_fingerprint(rule_id: str, condition: dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(condition, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return f"{rule_id}:{digest}"


async def _evaluate_ai_condition(condition: dict[str, Any], message: Message, analysis: AIAnalysis | None, cache_key: str) -> bool:
    settings = get_settings()
    if not settings.ai_enabled:
        return False

    cache: dict[str, bool] = {}
    if analysis is not None:
        try:
            cache = json.loads(analysis.rule_ai_conditions_json or "{}")
        except json.JSONDecodeError:
            cache = {}
        if cache_key in cache:
            return bool(cache[cache_key])

    provider = get_llm_provider()
    body = truncate_for_ai(message.body_text or "", settings.max_body_chars_for_ai)
    user_prompt = (
        f"判定基準: {condition.get('value', '')}\n\n"
        f"件名: {message.subject}\n"
        f"送信元: {message.sender_name} <{message.sender_address}>\n"
        f"本文:\n{body}"
    )
    try:
        raw, _usage = await provider.complete_json(system_prompt=_AI_CONDITION_SYSTEM_PROMPT, user_prompt=user_prompt)
        matched = bool(raw.get("matches")) if isinstance(raw, dict) else False
    except (LLMProviderError, ValidationError) as exc:
        logger.warning("rule_engine: ai_prompt condition failed (%s), treating as not matched", exc)
        matched = False

    if analysis is not None:
        cache[cache_key] = matched
        analysis.rule_ai_conditions_json = json.dumps(cache, ensure_ascii=False)

    return matched


async def evaluate_rules(db: Session, message: Message, analysis: AIAnalysis | None) -> list[RuleFireResult]:
    rules = db.query(Rule).filter(Rule.is_active.is_(True)).order_by(Rule.priority.asc()).all()
    fired: list[RuleFireResult] = []

    for rule in rules:
        conditions = json.loads(rule.conditions_json or "[]")
        if not conditions:
            continue

        checks: list[bool] = []
        for condition in conditions:
            if condition.get("field") == AI_PROMPT_FIELD:
                cache_key = _condition_fingerprint(rule.id, condition)
                checks.append(await _evaluate_ai_condition(condition, message, analysis, cache_key))
            else:
                checks.append(_evaluate_condition(condition, message, analysis))

        matched = all(checks) if rule.match_mode == "all" else any(checks)
        if matched:
            fired.append(RuleFireResult(rule=rule, actions=json.loads(rule.actions_json or "[]")))

    if analysis is not None:
        db.add(analysis)

    return fired


def apply_actions(db: Session, message: Message, fired: list[RuleFireResult]) -> None:
    """Executes what evaluate_rules() found. Two built-in actions today:
    "tag" (adds a MessageTag with source="rule", confidence 1.0 — a rule
    match is a certainty, not a probabilistic guess) and "move_to_folder"
    (the user-configurable alternative/override to analysis_service's
    hardcoded category->folder heuristic — "どんな基準でフォルダ分けするの
    かも設定できるように": conditions here can match on mail_type,
    priority, sender, subject, an AI-judged free-text prompt, etc., and the
    destination folder is whatever the user typed, so it isn't limited to
    the built-in 案件/人材/重要/要返信/Junk set). Rules run after the
    heuristic in analysis_service, so a matching rule always has the final
    say on which folder a message ends up in. Any other action type (e.g.
    "notify_slack", "webhook") is left for a plugin to interpret: see
    services/plugin_manager.py's dispatch, which runs alongside this and
    receives the same message/classification — a matched rule with an
    unrecognized action type is a no-op here rather than an error, since
    plugins are the intended extension point.
    """
    for result in fired:
        for action in result.actions:
            action_type = action.get("type")
            if action_type == "tag":
                _apply_tag_action(db, message, action.get("params", {}).get("tag"))
            elif action_type == "move_to_folder":
                _apply_move_to_folder_action(db, message, action.get("params", {}).get("folder"))

    # Committed unconditionally (not just `if fired`) so the ai_prompt cache
    # evaluate_rules() staged onto `analysis` — via db.add(analysis), even
    # when no rule ended up matching — is persisted too; otherwise a rule
    # whose ai_prompt condition evaluates false every time would re-spend an
    # LLM call on every single re-open of the message.
    db.commit()


def _apply_move_to_folder_action(db: Session, message: Message, folder: str | None) -> None:
    if not folder:
        return
    message.folder = folder


def _apply_tag_action(db: Session, message: Message, tag_name: str | None) -> None:
    if not tag_name:
        return

    tag = db.query(Tag).filter(Tag.name == tag_name).one_or_none()
    if tag is None:
        tag = Tag(name=tag_name)
        db.add(tag)
        db.flush()

    existing = (
        db.query(MessageTag)
        .filter(MessageTag.message_id == message.id, MessageTag.tag_id == tag.id)
        .one_or_none()
    )
    if existing is None:
        db.add(MessageTag(message_id=message.id, tag_id=tag.id, confidence=1.0, source="rule"))
