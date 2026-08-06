"""Regression coverage: queue.process_next() was only ever invoked by
POST /ai/queue/process (a manual/test-only route the frontend never calls)
— nothing drained the AnalysisQueueItem backlog that sync_service enqueues
on every synced message, so automatic classification/extraction never
actually happened after a real mail sync. main.py's lifespan now runs a
background asyncio task that polls the queue; this verifies the task
actually starts and drains a pending job without any manual trigger.
"""
from __future__ import annotations

import asyncio
import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


async def _wait_until_done(get_status, timeout: float = 5.0) -> str:
    elapsed = 0.0
    step = 0.05
    while elapsed < timeout:
        status = get_status()
        if status in ("done", "failed"):
            return status
        await asyncio.sleep(step)
        elapsed += step
    raise AssertionError("queue item never left pending/running within timeout")


def test_enqueued_analyze_job_is_drained_without_manual_trigger():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message
        from app.db.models.ai import AnalysisQueueItem
        from app.services import queue

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
        db.add(message)
        db.commit()
        message_id = message.id

        item = queue.enqueue(db, message_id, "analyze")
        item_id = item.id
        db.close()

        def get_status() -> str:
            session = SessionLocal()
            try:
                return session.query(AnalysisQueueItem).filter(AnalysisQueueItem.id == item_id).one().status
            finally:
                session.close()

        status = asyncio.run(_wait_until_done(get_status))
        assert status == "done"

        db = SessionLocal()
        from app.db.models.ai import AIAnalysis

        assert db.query(AIAnalysis).filter(AIAnalysis.message_id == message_id).one_or_none() is not None
        db.close()
