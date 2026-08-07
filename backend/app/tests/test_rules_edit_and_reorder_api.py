"""Coverage for the rule-management gaps a real user hit: no way to edit a
rule after creating it (only toggle/delete), and no way to see or change the
evaluation order beyond typing a raw priority number at creation time
("編集機能と優先度の並び替えができるように"). PUT /rules/{id} covers the
former; PUT /rules/reorder covers the latter."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def _create_rule(client: TestClient, name: str, priority: int = 100) -> str:
    resp = client.post(
        "/rules",
        json={
            "name": name,
            "priority": priority,
            "conditions": [{"field": "subject", "operator": "contains", "value": "テスト"}],
            "actions": [{"type": "move_to_folder", "params": {"folder": "テスト用"}}],
        },
    )
    assert resp.status_code == 200
    return resp.json()["id"]


def test_update_rule_changes_name_conditions_and_actions():
    with _make_client() as client:
        rule_id = _create_rule(client, "元の名前")

        resp = client.put(
            f"/rules/{rule_id}",
            json={
                "name": "新しい名前",
                "description": "◯◯社は優先確認が必要なため",
                "match_mode": "any",
                "conditions": [
                    {"field": "sender_address", "operator": "contains", "value": "important-client"},
                    {"field": "ai_prompt", "operator": "matches", "value": "強いクレームが書かれている"},
                ],
                "actions": [{"type": "tag", "params": {"tag": "重要"}}],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "新しい名前"
        assert body["description"] == "◯◯社は優先確認が必要なため"
        assert body["match_mode"] == "any"
        assert len(body["conditions"]) == 2
        assert body["conditions"][1]["field"] == "ai_prompt"
        assert body["actions"] == [{"type": "tag", "params": {"tag": "重要"}}]

        # persisted, not just echoed back
        listed = client.get("/rules").json()
        assert listed[0]["name"] == "新しい名前"


def test_update_rule_partial_payload_only_changes_given_fields():
    with _make_client() as client:
        rule_id = _create_rule(client, "元の名前", priority=50)

        resp = client.put(f"/rules/{rule_id}", json={"priority": 5})
        assert resp.status_code == 200
        body = resp.json()
        assert body["priority"] == 5
        assert body["name"] == "元の名前"  # untouched


def test_update_rule_404s_for_unknown_id():
    with _make_client() as client:
        resp = client.put("/rules/does-not-exist", json={"name": "x"})
        assert resp.status_code == 404


def test_reorder_rules_reassigns_priority_by_position():
    with _make_client() as client:
        first = _create_rule(client, "A", priority=10)
        second = _create_rule(client, "B", priority=20)
        third = _create_rule(client, "C", priority=30)

        resp = client.put("/rules/reorder", json={"rule_ids": [third, first, second]})
        assert resp.status_code == 200
        ordered_ids = [r["id"] for r in resp.json()]
        assert ordered_ids == [third, first, second]

        listed = client.get("/rules").json()
        assert [r["id"] for r in listed] == [third, first, second]


def test_reorder_rules_rejects_a_payload_missing_an_existing_rule():
    with _make_client() as client:
        first = _create_rule(client, "A")
        _create_rule(client, "B")

        resp = client.put("/rules/reorder", json={"rule_ids": [first]})
        assert resp.status_code == 400


def test_reorder_rules_rejects_an_unknown_rule_id():
    with _make_client() as client:
        first = _create_rule(client, "A")

        resp = client.put("/rules/reorder", json={"rule_ids": [first, "does-not-exist"]})
        assert resp.status_code == 404
