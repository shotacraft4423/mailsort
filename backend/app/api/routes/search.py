from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import search_service

router = APIRouter(prefix="/search", tags=["search"])


class MessageHit(BaseModel):
    id: str
    subject: str
    sender_address: str

    model_config = {"from_attributes": True}


@router.get("", response_model=list[MessageHit])
def full_text_search(
    q: str, limit: int = 50, folder: str | None = None, account_id: str | None = None, db: Session = Depends(get_db)
) -> list:
    backend = search_service.SqliteLikeBackend()
    return backend.search(db, q, limit=limit, folder=folder, account_id=account_id)


@router.get("/natural", response_model=list[MessageHit])
async def natural_search(
    q: str, limit: int = 50, folder: str | None = None, account_id: str | None = None, db: Session = Depends(get_db)
) -> list:
    return await search_service.ai_search(db, q, limit=limit, folder=folder, account_id=account_id)
