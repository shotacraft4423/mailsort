"""Coverage for /folders: user-manageable custom folders beyond the
built-in 案件/人材/重要/要返信/Junk set — "フォルダの追加削除...にも対応して".
Deleting a folder moves any mail still filed there back to INBOX instead
of leaving it stranded."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_create_and_list_custom_folder():
    with _make_client() as client:
        resp = client.post("/folders", json={"name": "最重要顧客"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "最重要顧客"

        list_resp = client.get("/folders")
        assert [f["name"] for f in list_resp.json()] == ["最重要顧客"]


def test_creating_the_same_folder_name_twice_is_idempotent():
    with _make_client() as client:
        first = client.post("/folders", json={"name": "重複テスト"})
        second = client.post("/folders", json={"name": "重複テスト"})
        assert first.json()["id"] == second.json()["id"]
        assert len(client.get("/folders").json()) == 1


def test_empty_folder_name_is_rejected():
    with _make_client() as client:
        resp = client.post("/folders", json={"name": "   "})
        assert resp.status_code == 400


def test_deleting_a_folder_moves_its_messages_back_to_inbox():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        create_resp = client.post("/folders", json={"name": "最重要顧客"})
        folder_id = create_resp.json()["id"]

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", folder="最重要顧客")
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        del_resp = client.delete(f"/folders/{folder_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["messages_moved_to_inbox"] == 1

        assert client.get("/folders").json() == []

        db = SessionLocal()
        assert db.query(Message).filter(Message.id == message_id).one().folder == "INBOX"
        db.close()


def test_delete_folder_404s_for_unknown_id():
    with _make_client() as client:
        resp = client.delete("/folders/does-not-exist")
        assert resp.status_code == 404
