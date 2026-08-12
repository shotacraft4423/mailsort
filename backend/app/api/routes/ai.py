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
    feedback_service,
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


@router.post("/reroute-folders")
def reroute_folders(db: Session = Depends(get_db)) -> dict:
    """Bulk-corrects folder placement for every already-classified message
    using its cached classification — no LLM call, so it's safe to run any
    time a past auto-routing bug (or a settings change) has left mail
    sitting in the wrong category folder. See
    analysis_service.reroute_classified_messages."""
    moved = analysis_service.reroute_classified_messages(db)
    return {"moved": moved}


@router.post("/reclassify-fallback")
async def reclassify_fallback(
    folder: str | None = None, account_id: str | None = None, limit: int = 50, db: Session = Depends(get_db)
) -> dict:
    """Force-reclassifies just the messages currently flagged is_fallback —
    a targeted retry for "うちのメールが全部オフライン分類のまま" once the
    underlying AI connection issue is believed fixed, without re-spending
    tokens on mail that was already classified successfully. See
    analysis_service.reclassify_fallback_messages."""
    return await analysis_service.reclassify_fallback_messages(db, folder=folder, account_id=account_id, limit=limit)


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


class CorrectClassificationRequest(BaseModel):
    corrected_mail_type: str
    note: str = ""


@router.post("/messages/{message_id}/correct-classification")
def correct_classification(message_id: str, payload: CorrectClassificationRequest, db: Session = Depends(get_db)) -> dict:
    """AI学習モード: records a user correction ("これは案件" etc.), applies it
    to the message's current classification immediately, and makes it
    available as a few-shot example for future similar emails — see
    services/feedback_service.py."""
    message = _get_message(db, message_id)
    feedback = feedback_service.record_correction(db, message, payload.corrected_mail_type, note=payload.note)
    return {"id": feedback.id, "corrected_mail_type": feedback.corrected_mail_type}


class MarkReplyNotNeededRequest(BaseModel):
    note: str = ""


@router.post("/messages/{message_id}/mark-reply-not-needed")
def mark_reply_not_needed(message_id: str, payload: MarkReplyNotNeededRequest, db: Session = Depends(get_db)) -> dict:
    """"返信不要ボタン" — corrects reply_required=False on the message's
    current classification immediately (dropping it off the dashboard's
    overdue-reply reminder) and records it as a few-shot example, mirroring
    correct_classification()'s pattern for mail_type corrections."""
    message = _get_message(db, message_id)
    feedback = feedback_service.record_reply_not_needed(db, message, note=payload.note)
    return {"id": feedback.id}


@router.get("/reply-tones")
def reply_tones() -> list[str]:
    return reply_suggestion_service.TONES


@router.post("/queue/process")
async def process_queue_item(db: Session = Depends(get_db)) -> dict:
    item = await queue.process_next(db)
    if item is None:
        return {"status": "empty"}
    return {"status": item.status, "task": item.task, "message_id": item.message_id, "last_error": item.last_error}
