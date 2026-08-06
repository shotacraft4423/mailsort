"""Regression coverage: there was no way to dismiss a meeting the user
doesn't need to attend — the calendar view always showed every extracted
meeting forever. Adds PATCH /meetings/{id} (is_hidden) and a default
include_hidden=false filter on GET /meetings."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def _seed_meeting(client: TestClient) -> str:
    from app.db.session import SessionLocal
    from app.db.models.meeting import Meeting

    db = SessionLocal()
    meeting = Meeting(title="定例会議", platform="meet", join_url="https://meet.google.com/abc-defg-hij")
    db.add(meeting)
    db.commit()
    meeting_id = meeting.id
    db.close()
    return meeting_id


def test_hidden_meeting_is_excluded_by_default_but_included_with_flag():
    with _make_client() as client:
        meeting_id = _seed_meeting(client)

        resp = client.patch(f"/meetings/{meeting_id}", json={"is_hidden": True})
        assert resp.status_code == 200
        assert resp.json()["is_hidden"] is True

        assert all(m["id"] != meeting_id for m in client.get("/meetings").json())
        assert any(m["id"] == meeting_id for m in client.get("/meetings", params={"include_hidden": True}).json())


def test_update_meeting_404s_for_unknown_id():
    with _make_client() as client:
        resp = client.patch("/meetings/does-not-exist", json={"is_hidden": True})
        assert resp.status_code == 404


def test_meeting_out_includes_source_message_id_for_calendar_jump_link():
    """会議のタブからソースになっているメールに飛べるように — the calendar
    view needs the originating message id on every meeting row to render a
    "元のメールを開く" link."""
    with _make_client() as client:
        from app.db.models.email import EmailAccount, Message
        from app.db.models.meeting import Meeting
        from app.db.session import SessionLocal

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com")
        db.add(message)
        db.flush()
        meeting = Meeting(source_message_id=message.id, title="定例会議", platform="meet", join_url="https://meet.google.com/abc-defg-hij")
        db.add(meeting)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get("/meetings")
        assert resp.status_code == 200
        assert resp.json()[0]["source_message_id"] == message_id
