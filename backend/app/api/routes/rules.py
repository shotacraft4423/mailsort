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
    description: str
    is_active: bool
    priority: int
    match_mode: str
    conditions: list[dict]
    actions: list[dict]


class RuleCreate(BaseModel):
    name: str
    description: str = ""
    priority: int = 100
    match_mode: str = "all"
    conditions: list[RuleCondition]
    actions: list[RuleAction]


class RuleUpdate(BaseModel):
    """All fields optional so a client can PATCH-like update just what it
    changed — used both by the full rule-edit form ("編集機能") and by the
    reorder endpoint below, which is really just a repeated priority-only
    update."""

    name: str | None = None
    description: str | None = None
    priority: int | None = None
    match_mode: str | None = None
    conditions: list[RuleCondition] | None = None
    actions: list[RuleAction] | None = None


class ReorderRequest(BaseModel):
    # Rule ids in the desired top-to-bottom (first-to-run) order. Every
    # existing rule id must be present — this replaces the priority of each
    # one wholesale rather than accepting a partial reordering, so a
    # dropped or duplicated id would silently strand a rule.
    rule_ids: list[str]


def _to_out(rule: Rule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        name=rule.name,
        description=rule.description,
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
        description=payload.description,
        priority=payload.priority,
        match_mode=payload.match_mode,
        conditions_json=json.dumps([c.model_dump() for c in payload.conditions], ensure_ascii=False),
        actions_json=json.dumps([a.model_dump() for a in payload.actions], ensure_ascii=False),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.put("/reorder", response_model=list[RuleOut])
def reorder_rules(payload: ReorderRequest, db: Session = Depends(get_db)) -> list[RuleOut]:
    """"優先度の並び替えができるように" — the priority field always existed,
    but only as a number typed in at creation time with no way to see or
    change the resulting order relative to other rules. The frontend sends
    the full list of rule ids in the new top-to-bottom order; this assigns
    priority = (index + 1) * 10 (leaving gaps, same convention a manually
    typed priority already implied) rather than exposing raw priority
    numbers as the thing being dragged around."""
    rules = {r.id: r for r in db.query(Rule).all()}
    missing = [rid for rid in payload.rule_ids if rid not in rules]
    if missing:
        raise HTTPException(status_code=404, detail=f"rule(s) not found: {', '.join(missing)}")
    if len(payload.rule_ids) != len(rules):
        raise HTTPException(status_code=400, detail="rule_ids must include every existing rule")

    for index, rule_id in enumerate(payload.rule_ids):
        rules[rule_id].priority = (index + 1) * 10
    db.commit()
    return [_to_out(r) for r in db.query(Rule).order_by(Rule.priority.asc()).all()]


@router.put("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: str, payload: RuleUpdate, db: Session = Depends(get_db)) -> RuleOut:
    rule = db.query(Rule).filter(Rule.id == rule_id).one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")

    if payload.name is not None:
        rule.name = payload.name
    if payload.description is not None:
        rule.description = payload.description
    if payload.priority is not None:
        rule.priority = payload.priority
    if payload.match_mode is not None:
        rule.match_mode = payload.match_mode
    if payload.conditions is not None:
        rule.conditions_json = json.dumps([c.model_dump() for c in payload.conditions], ensure_ascii=False)
    if payload.actions is not None:
        rule.actions_json = json.dumps([a.model_dump() for a in payload.actions], ensure_ascii=False)

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


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, db: Session = Depends(get_db)) -> dict:
    rule = db.query(Rule).filter(Rule.id == rule_id).one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    db.delete(rule)
    db.commit()
    return {"status": "deleted"}
