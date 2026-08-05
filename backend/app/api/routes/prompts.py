from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.ai import PromptTemplate, PromptVersion

router = APIRouter(prefix="/prompts", tags=["prompts"])


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
