from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models.email import Message
from app.services import (
    analysis_service,
    classification_service,
    extraction_service,
    queue,
    reply_suggestion_service,
    summarization_service,
)
from app.services.summarization_service import SummaryLevel

router = APIRouter(prefix="/ai", tags=["ai"])


def _get_message(db: Session, message_id: str) -> Message:
    message = db.query(Message).filter(Message.id == message_id).one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    return message


@router.post("/messages/{message_id}/analyze")
async def analyze(message_id: str, force: bool = False, db: Session = Depends(get_db)) -> dict:
    """Preferred entry point: classification + extraction in one LLM call.
    See analysis_service's docstring for why this is cheaper than calling
    /classify then /extract separately."""
    message = _get_message(db, message_id)
    outcome = await analysis_service.analyze_message(db, message, force=force)
    return {
        "from_cache": outcome.from_cache,
        "is_fallback": outcome.is_fallback,
        "provider_used": outcome.analysis.provider_used,
        "classification": outcome.classification.model_dump(),
        "extraction": outcome.extraction.model_dump(),
    }


@router.post("/messages/{message_id}/classify")
async def classify(message_id: str, force: bool = False, db: Session = Depends(get_db)) -> dict:
    """Classification only, no extraction. Prefer POST .../analyze for the
    combined (cheaper) call; this stays for testing the classification
    prompt in isolation."""
    message = _get_message(db, message_id)
    outcome = await classification_service.classify_message(db, message, force=force)
    return {
        "from_cache": outcome.from_cache,
        "is_fallback": outcome.analysis.is_fallback,
        "provider_used": outcome.analysis.provider_used,
        "result": outcome.result.model_dump(),
    }


@router.post("/messages/{message_id}/extract")
async def extract(message_id: str, db: Session = Depends(get_db)) -> dict:
    message = _get_message(db, message_id)
    outcome = await extraction_service.extract_message(db, message)
    return {"is_fallback": outcome.is_fallback, "result": outcome.result.model_dump()}


class SummarizeRequest(BaseModel):
    level: SummaryLevel = "3line"


@router.post("/messages/{message_id}/summarize")
async def summarize(message_id: str, payload: SummarizeRequest, db: Session = Depends(get_db)) -> dict:
    message = _get_message(db, message_id)
    text = await summarization_service.summarize_message(db, message, payload.level)
    return {"level": payload.level, "summary": text}


class ReplyRequest(BaseModel):
    tone: str
    style_hint: str = ""


@router.post("/messages/{message_id}/reply-suggestion")
async def reply_suggestion(message_id: str, payload: ReplyRequest, db: Session = Depends(get_db)) -> dict:
    message = _get_message(db, message_id)
    draft = await reply_suggestion_service.suggest_reply(db, message, payload.tone, style_hint=payload.style_hint)
    return {"tone": payload.tone, "draft": draft}


@router.get("/reply-tones")
def reply_tones() -> list[str]:
    return reply_suggestion_service.TONES


@router.post("/queue/process")
async def process_queue_item(db: Session = Depends(get_db)) -> dict:
    item = await queue.process_next(db)
    if item is None:
        return {"status": "empty"}
    return {"status": item.status, "task": item.task, "message_id": item.message_id, "last_error": item.last_error}
