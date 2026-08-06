"""Coverage for POST /ai/reroute-folders — the "すでに割り振られてしまった
メールの再振り分けを行えるようにして" bulk-fix endpoint. Unlike bulk-classify
(which only ever looks at whatever folder is currently open), this walks
every already-classified message regardless of its current folder and
re-applies the routing heuristic straight from the cached classification,
with no LLM call involved."""
from __future__ import annotations

import json
import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_reroute_folders_moves_a_message_stuck_in_the_wrong_category_folder():
    with _make_client() as client:
        from app.db.models.ai import AIAnalysis
        from app.db.models.email import EmailAccount, Message
        from app.db.session import SessionLocal

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(
            account_id=account.id,
            message_uid="1",
            subject="人材のご紹介",
            sender_address="a@b.com",
            body_text="人材のご紹介です。",
            folder="案件",
        )
        db.add(message)
        db.flush()
        db.add(
            AIAnalysis(
                message_id=message.id,
                content_hash="irrelevant",
                provider_used="local_mock",
                classification_json=json.dumps(
                    {"mail_type": "人材紹介", "categories": [{"label": "人材紹介", "confidence": 1.0}], "reply_required": False}
                ),
                extraction_json="{}",
            )
        )
        db.commit()
        message_id = message.id
        db.close()

        resp = client.post("/ai/reroute-folders")
        assert resp.status_code == 200
        assert resp.json() == {"moved": 1}

        db = SessionLocal()
        assert db.query(Message).filter(Message.id == message_id).one().folder == "人材"
        db.close()
