from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
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
    ends_at: datetime | None
    is_rescheduled: bool
    supersedes_meeting_id: str | None
    is_hidden: bool

    model_config = {"from_attributes": True}


class MeetingUpdate(BaseModel):
    is_hidden: bool


@router.get("", response_model=list[MeetingOut])
def list_meetings(include_hidden: bool = False, db: Session = Depends(get_db)) -> list[Meeting]:
    q = db.query(Meeting)
    if not include_hidden:
        q = q.filter(Meeting.is_hidden.is_(False))
    return q.order_by(Meeting.starts_at.desc()).all()


@router.patch("/{meeting_id}", response_model=MeetingOut)
def update_meeting(meeting_id: str, payload: MeetingUpdate, db: Session = Depends(get_db)) -> Meeting:
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).one_or_none()
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    meeting.is_hidden = payload.is_hidden
    db.commit()
    db.refresh(meeting)
    return meeting
