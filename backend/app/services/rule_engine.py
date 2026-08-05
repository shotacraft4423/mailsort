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
