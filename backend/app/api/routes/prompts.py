from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.ai import PromptTemplate, PromptVersion
from app.services import classification_service, extraction_service

router = APIRouter(prefix="/prompts", tags=["prompts"])

# Only these two tasks are actually read by the pipeline (analysis_service /
# classification_service / extraction_service consult get_active_prompt()
# for them) — see each module's DEFAULT_SYSTEM_PROMPT / DEFAULT_USER_PROMPT_
# TEMPLATE. summary/reply_suggestion/duplicate_check/chat are handled by
# their own services with prompts that aren't yet wired to PromptTemplate,
# so a template created for those tasks would silently do nothing.
_DEFAULTS_BY_TASK = {
    classification_service.TASK: (classification_service.DEFAULT_SYSTEM_PROMPT, classification_service.DEFAULT_USER_PROMPT_TEMPLATE),
    extraction_service.TASK: (extraction_service.DEFAULT_SYSTEM_PROMPT, extraction_service.DEFAULT_USER_PROMPT_TEMPLATE),
}


class PromptDefaultsOut(BaseModel):
    task: str
    system_prompt: str
    user_prompt_template: str


class PromptVersionOut(BaseModel):
    id: str
    version_number: int
    system_prompt: str
    user_prompt_template: str
    notes: str

    model_config = {"from_attributes": True}


class PromptTemplateOut(BaseModel):
    id: str
    name: str
    task: str
    is_active: bool
    active_version_id: str | None
    versions: list[PromptVersionOut]

    model_config = {"from_attributes": True}


class PromptTemplateCreate(BaseModel):
    name: str
    task: str
    system_prompt: str
    user_prompt_template: str


class PromptVersionCreate(BaseModel):
    system_prompt: str
    user_prompt_template: str
    notes: str = ""
    activate: bool = True


@router.get("", response_model=list[PromptTemplateOut])
def list_prompts(task: str | None = None, db: Session = Depends(get_db)) -> list[PromptTemplate]:
    q = db.query(PromptTemplate)
    if task:
        q = q.filter(PromptTemplate.task == task)
    return q.all()


@router.get("/defaults", response_model=PromptDefaultsOut)
def get_defaults(task: str) -> PromptDefaultsOut:
    """Lets the "new template" form prefill from the prompt the backend
    actually falls back to today, so a user isn't asked to write a
    classification/extraction prompt from a blank textarea with no idea
    what shape of instructions belongs there."""
    defaults = _DEFAULTS_BY_TASK.get(task)
    if defaults is None:
        raise HTTPException(status_code=404, detail=f"no default prompt for task {task!r}")
    system_prompt, user_prompt_template = defaults
    return PromptDefaultsOut(task=task, system_prompt=system_prompt, user_prompt_template=user_prompt_template)


@router.post("", response_model=PromptTemplateOut)
def create_prompt(payload: PromptTemplateCreate, db: Session = Depends(get_db)) -> PromptTemplate:
    template = PromptTemplate(name=payload.name, task=payload.task)
    db.add(template)
    db.flush()

    version = PromptVersion(
        template_id=template.id,
        version_number=1,
        system_prompt=payload.system_prompt,
        user_prompt_template=payload.user_prompt_template,
    )
    db.add(version)
    db.flush()
    template.active_version_id = version.id
    db.commit()
    db.refresh(template)
    return template


@router.post("/{template_id}/versions", response_model=PromptVersionOut)
def add_version(template_id: str, payload: PromptVersionCreate, db: Session = Depends(get_db)) -> PromptVersion:
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="prompt template not found")

    next_number = max((v.version_number for v in template.versions), default=0) + 1
    version = PromptVersion(
        template_id=template.id,
        version_number=next_number,
        system_prompt=payload.system_prompt,
        user_prompt_template=payload.user_prompt_template,
        notes=payload.notes,
    )
    db.add(version)
    db.flush()
    if payload.activate:
        template.active_version_id = version.id
    db.commit()
    db.refresh(version)
    return version


@router.delete("/{template_id}")
def delete_prompt(template_id: str, db: Session = Depends(get_db)) -> dict:
    template = db.query(PromptTemplate).filter(PromptTemplate.id == template_id).one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="prompt template not found")
    db.delete(template)  # cascades to versions (see PromptTemplate.versions' cascade="all, delete-orphan")
    db.commit()
    return {"status": "deleted"}
