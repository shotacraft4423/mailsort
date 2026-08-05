"""Resolves the GUI-editable prompt (see api/routes/prompts.py) that a
pipeline stage should use, falling back to that module's hardcoded default
when no PromptTemplate has been activated for the task yet. This is the
seam that makes "プロンプト・分類ルール・タグをGUIから編集可能" actually
take effect instead of just being stored and ignored.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.db.models.ai import PromptTemplate, PromptVersion

_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(template: str, context: dict[str, str]) -> str:
    """Minimal `{{ variable }}` substitution. Deliberately not a full Jinja
    engine (no loops/conditionals) — prompt templates here are flat
    field-interpolation strings, and pulling in a templating dependency for
    that would be more machinery than the feature needs."""
    return _VAR_RE.sub(lambda m: context.get(m.group(1), ""), template)


def get_active_prompt(db: Session, task: str) -> PromptVersion | None:
    template = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.task == task, PromptTemplate.is_active.is_(True))
        .order_by(PromptTemplate.created_at.desc())
        .first()
    )
    if template is None or template.active_version_id is None:
        return None
    return db.query(PromptVersion).filter(PromptVersion.id == template.active_version_id).one_or_none()
