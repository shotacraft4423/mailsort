from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.rule import Rule

router = APIRouter(prefix="/rules", tags=["rules"])


class RuleCondition(BaseModel):
    field: str
    operator: str
    value: str


class RuleAction(BaseModel):
    type: str
    params: dict = {}


class RuleOut(BaseModel):
    id: str
    name: str
    is_active: bool
    priority: int
    match_mode: str
    conditions: list[dict]
    actions: list[dict]


class RuleCreate(BaseModel):
    name: str
    priority: int = 100
    match_mode: str = "all"
    conditions: list[RuleCondition]
    actions: list[RuleAction]


def _to_out(rule: Rule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        name=rule.name,
        is_active=rule.is_active,
        priority=rule.priority,
        match_mode=rule.match_mode,
        conditions=json.loads(rule.conditions_json or "[]"),
        actions=json.loads(rule.actions_json or "[]"),
    )


@router.get("", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db)) -> list[RuleOut]:
    return [_to_out(r) for r in db.query(Rule).order_by(Rule.priority.asc()).all()]


@router.post("", response_model=RuleOut)
def create_rule(payload: RuleCreate, db: Session = Depends(get_db)) -> RuleOut:
    rule = Rule(
        name=payload.name,
        priority=payload.priority,
        match_mode=payload.match_mode,
        conditions_json=json.dumps([c.model_dump() for c in payload.conditions], ensure_ascii=False),
        actions_json=json.dumps([a.model_dump() for a in payload.actions], ensure_ascii=False),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.patch("/{rule_id}/toggle", response_model=RuleOut)
def toggle_rule(rule_id: str, db: Session = Depends(get_db)) -> RuleOut:
    rule = db.query(Rule).filter(Rule.id == rule_id).one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    rule.is_active = not rule.is_active
    db.commit()
    db.refresh(rule)
    return _to_out(rule)
