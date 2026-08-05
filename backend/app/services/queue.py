"""DB-backed background job queue for AI analysis.

Kept deliberately simple (poll + claim via UPDATE) so the MVP has zero extra
infrastructure dependencies (no Redis/broker). `process_next` is meant to be
called from a periodic background task (see api/main.py's startup event) or
manually via POST /queue/process for testing. Swap this module for a
Celery+Redis-backed implementation at commercial scale — the producer API
(`enqueue`) is the seam that keeps callers unaffected by that change.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.ai import AnalysisQueueItem
from app.db.models.email import Message
from app.services import classification_service, extraction_service, summarization_service

_MAX_ATTEMPTS = 3


def enqueue(db: Session, message_id: str, task: str) -> AnalysisQueueItem:
    item = AnalysisQueueItem(message_id=message_id, task=task, status="pending")
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


async def process_next(db: Session) -> AnalysisQueueItem | None:
    item = (
        db.query(AnalysisQueueItem)
        .filter(AnalysisQueueItem.status == "pending")
        .order_by(AnalysisQueueItem.created_at.asc())
        .first()
    )
    if item is None:
        return None

    item.status = "running"
    item.attempts += 1
    db.commit()

    message = db.query(Message).filter(Message.id == item.message_id).one_or_none()
    if message is None:
        item.status = "failed"
        item.last_error = "message not found"
        db.commit()
        return item

    try:
        if item.task == "classify":
            await classification_service.classify_message(db, message)
        elif item.task == "extract":
            await extraction_service.extract_message(db, message)
        elif item.task in ("summarize_3line", "summarize_10line", "summarize_detailed"):
            level = item.task.removeprefix("summarize_")
            level = {"3line": "3line", "10line": "10line", "detailed": "detailed"}[level]
            await summarization_service.summarize_message(db, message, level)  # type: ignore[arg-type]
        else:
            raise ValueError(f"unknown task {item.task!r}")
        item.status = "done"
        item.last_error = None
    except Exception as exc:  # noqa: BLE001 - queue must never crash the worker loop
        item.last_error = str(exc)
        item.status = "pending" if item.attempts < _MAX_ATTEMPTS else "failed"

    db.commit()
    return item
