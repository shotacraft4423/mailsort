"""No-code rule engine ("特定企業は必ず重要", "特定キーワードはSlack通知").

Rules run after AI classification and can add tags / raise priority / fire
plugin actions, but never depend on AI being available — every condition
here reads from plain Message fields (plus AI-derived fields when present),
so rules keep working even with AI disabled.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.ai import AIAnalysis
from app.db.models.email import Message
from app.db.models.rule import Rule
from app.db.models.tag import MessageTag, Tag

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


def evaluate_rules(db: Session, message: Message, analysis: AIAnalysis | None) -> list[RuleFireResult]:
    rules = db.query(Rule).filter(Rule.is_active.is_(True)).order_by(Rule.priority.asc()).all()
    fired: list[RuleFireResult] = []

    for rule in rules:
        conditions = json.loads(rule.conditions_json or "[]")
        if not conditions:
            continue
        checks = [_evaluate_condition(c, message, analysis) for c in conditions]
        matched = all(checks) if rule.match_mode == "all" else any(checks)
        if matched:
            fired.append(RuleFireResult(rule=rule, actions=json.loads(rule.actions_json or "[]")))

    return fired


def apply_actions(db: Session, message: Message, fired: list[RuleFireResult]) -> None:
    """Executes what evaluate_rules() found. Two built-in actions today:
    "tag" (adds a MessageTag with source="rule", confidence 1.0 — a rule
    match is a certainty, not a probabilistic guess) and "move_to_folder"
    (the user-configurable alternative/override to analysis_service's
    hardcoded category->folder heuristic — "どんな基準でフォルダ分けするの
    かも設定できるように": conditions here can match on mail_type,
    priority, sender, subject, etc., and the destination folder is
    whatever the user typed, so it isn't limited to the built-in 案件/
    人材/重要/要返信/Junk set). Rules run after the heuristic in
    analysis_service, so a matching rule always has the final say on
    which folder a message ends up in. Any other action type (e.g.
    "notify_slack", "webhook") is left for a plugin to interpret: see
    services/plugin_manager.py's dispatch, which runs alongside this and
    receives the same message/classification — a matched rule with an
    unrecognized action type is a no-op here rather than an error, since
    plugins are the intended extension point.
    """
    if not fired:
        return

    for result in fired:
        for action in result.actions:
            action_type = action.get("type")
            if action_type == "tag":
                _apply_tag_action(db, message, action.get("params", {}).get("tag"))
            elif action_type == "move_to_folder":
                _apply_move_to_folder_action(db, message, action.get("params", {}).get("folder"))

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
