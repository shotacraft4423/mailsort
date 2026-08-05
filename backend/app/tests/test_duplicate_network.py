from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient

from app.db.models.deal import Deal
from app.services.duplicate_detection_service import DuplicateMatch, persist_deal_duplicates


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


def test_persist_deal_duplicates_sets_cluster_root(db_session):
    root = Deal(title="Java案件")
    member = Deal(title="Javaエンジニア案件")
    db_session.add_all([root, member])
    db_session.commit()

    matches = [DuplicateMatch(other_id=member.id, similarity=0.9, relation="candidate", reason="similar")]
    persist_deal_duplicates(db_session, root, matches)

    db_session.refresh(member)
    assert member.duplicate_of_id == root.id
    assert member.duplicate_relation == "candidate"


def test_persist_deal_duplicates_does_not_reassign_existing_cluster(db_session):
    other_root = Deal(title="別クラスタのルート")
    member = Deal(title="既にリンク済み")
    db_session.add_all([other_root, member])
    db_session.flush()
    member.duplicate_of_id = other_root.id
    member.duplicate_relation = "exact"
    db_session.commit()

    new_root = Deal(title="新しいルート候補")
    db_session.add(new_root)
    db_session.commit()

    matches = [DuplicateMatch(other_id=member.id, similarity=0.95, relation="exact", reason="x")]
    persist_deal_duplicates(db_session, new_root, matches)

    db_session.refresh(member)
    assert member.duplicate_of_id == other_root.id  # unchanged


def test_persist_deal_duplicates_ignores_different_relation(db_session):
    root = Deal(title="A")
    other = Deal(title="B")
    db_session.add_all([root, other])
    db_session.commit()

    matches = [DuplicateMatch(other_id=other.id, similarity=0.5, relation="different", reason="unrelated")]
    persist_deal_duplicates(db_session, root, matches)

    db_session.refresh(other)
    assert other.duplicate_of_id is None


def test_network_endpoint_returns_cluster_with_company_names():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.company import Company

        db = SessionLocal()
        company_a = Company(name="A社")
        company_b = Company(name="B社")
        db.add_all([company_a, company_b])
        db.flush()
        root = Deal(title="Java案件", company_id=company_a.id, unit_price_min=60, unit_price_max=70)
        member = Deal(
            title="Javaエンジニア案件",
            company_id=company_b.id,
            unit_price_min=65,
            unit_price_max=75,
            duplicate_of_id=None,
        )
        db.add_all([root, member])
        db.flush()
        member.duplicate_of_id = root.id
        member.duplicate_relation = "candidate"
        db.commit()
        root_id = root.id
        db.close()

        resp = client.get(f"/deals/{root_id}/network")
        assert resp.status_code == 200
        data = resp.json()
        assert data["root_id"] == root_id
        assert data["company_count"] == 2
        labels = {n["company_name"] for n in data["nodes"]}
        assert labels == {"A社", "B社"}
        root_node = next(n for n in data["nodes"] if n["id"] == root_id)
        assert root_node["relation"] == "root"


def test_network_endpoint_works_from_a_member_deal_too():
    with _make_client() as client:
        from app.db.session import SessionLocal

        db = SessionLocal()
        root = Deal(title="root")
        member = Deal(title="member")
        db.add_all([root, member])
        db.flush()
        member.duplicate_of_id = root.id
        member.duplicate_relation = "exact"
        db.commit()
        root_id, member_id = root.id, member.id
        db.close()

        resp = client.get(f"/deals/{member_id}/network")
        assert resp.status_code == 200
        assert resp.json()["root_id"] == root_id
        assert len(resp.json()["nodes"]) == 2


def test_network_endpoint_single_deal_with_no_duplicates():
    with _make_client() as client:
        from app.db.session import SessionLocal

        db = SessionLocal()
        deal = Deal(title="単独案件")
        db.add(deal)
        db.commit()
        deal_id = deal.id
        db.close()

        resp = client.get(f"/deals/{deal_id}/network")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 1
        assert data["company_count"] == 1
