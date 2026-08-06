"""Coverage for GET /mail/folders (distinct in-use folder names, so a
custom folder created by a rule's move_to_folder action shows up in the
sidebar) and DELETE /rules/{id} (the admin screen had no way to remove a
rule — only create and toggle)."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_list_local_folders_returns_distinct_folders_in_use():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        db.add(Message(account_id=account.id, message_uid="1", subject="a", sender_address="a@b.com", folder="INBOX"))
        db.add(Message(account_id=account.id, message_uid="2", subject="b", sender_address="a@b.com", folder="最重要顧客"))
        db.add(Message(account_id=account.id, message_uid="3", subject="c", sender_address="a@b.com", folder="最重要顧客"))
        db.commit()
        db.close()

        resp = client.get("/mail/folders")
        assert resp.status_code == 200
        assert resp.json() == ["INBOX", "最重要顧客"]


def test_delete_rule_removes_it():
    with _make_client() as client:
        create_resp = client.post(
            "/rules",
            json={
                "name": "テストルール",
                "conditions": [{"field": "subject", "operator": "contains", "value": "テスト"}],
                "actions": [{"type": "move_to_folder", "params": {"folder": "テスト用"}}],
            },
        )
        assert create_resp.status_code == 200
        rule_id = create_resp.json()["id"]

        del_resp = client.delete(f"/rules/{rule_id}")
        assert del_resp.status_code == 200

        list_resp = client.get("/rules")
        assert all(r["id"] != rule_id for r in list_resp.json())


def test_delete_rule_404s_for_unknown_id():
    with _make_client() as client:
        resp = client.delete("/rules/does-not-exist")
        assert resp.status_code == 404
