from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.email import Message
from app.db.models.folder import CustomFolder

router = APIRouter(prefix="/folders", tags=["folders"])


class FolderCreate(BaseModel):
    name: str


class FolderOut(BaseModel):
    id: str
    name: str

    model_config = {"from_attributes": True}


@router.get("", response_model=list[FolderOut])
def list_custom_folders(db: Session = Depends(get_db)) -> list[CustomFolder]:
    return db.query(CustomFolder).order_by(CustomFolder.name).all()


@router.post("", response_model=FolderOut)
def create_custom_folder(payload: FolderCreate, db: Session = Depends(get_db)) -> CustomFolder:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="folder name must not be empty")
    existing = db.query(CustomFolder).filter(CustomFolder.name == name).one_or_none()
    if existing:
        return existing
    folder = CustomFolder(name=name)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


@router.delete("/{folder_id}")
def delete_custom_folder(folder_id: str, db: Session = Depends(get_db)) -> dict:
    folder = db.query(CustomFolder).filter(CustomFolder.id == folder_id).one_or_none()
    if folder is None:
        raise HTTPException(status_code=404, detail="folder not found")

    # Deleting the folder entry shouldn't delete mail — move anything
    # still filed there back to INBOX so it stays reachable instead of
    # becoming invisible (no longer shown in the sidebar, no longer
    # matched by folder="X" queries) the moment the folder disappears.
    moved = db.query(Message).filter(Message.folder == folder.name).update({Message.folder: "INBOX"})
    db.delete(folder)
    db.commit()
    return {"status": "deleted", "messages_moved_to_inbox": moved}
