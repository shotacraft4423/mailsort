from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.meeting import Meeting

router = APIRouter(prefix="/meetings", tags=["meetings"])


class MeetingOut(BaseModel):
    id: str
    title: str
    platform: str
    join_url: str
    starts_at: datetime | None
    is_rescheduled: bool
    supersedes_meeting_id: str | None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[MeetingOut])
def list_meetings(db: Session = Depends(get_db)) -> list[Meeting]:
    return db.query(Meeting).order_by(Meeting.starts_at.desc()).all()
