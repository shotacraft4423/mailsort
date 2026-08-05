from __future__ import annotations

import json

import pytest

from app.db.models.deal import Deal
from app.services.duplicate_detection_service import cosine_similarity, find_duplicate_deals


def test_cosine_similarity_identical_vectors_is_one():
    v = [1.0, 2.0, 3.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_similar_titles_are_flagged_as_duplicate_candidates(db_session, monkeypatch):
    # Lower the threshold: the offline hash embedding only captures token
    # overlap, not real semantics, so "Java案件" vs "Javaエンジニア案件" needs
    # a looser bar than the production default tuned for a real embedding
    # model.
    monkeypatch.setenv("MAILSORT_DUPLICATE_SIMILARITY_THRESHOLD", "0.2")
    from app.core.config import get_settings

    get_settings.cache_clear()

    deal_a = Deal(title="Java案件 東京 リモート可", skills_json=json.dumps(["Java", "Spring"]), location="東京")
    deal_b = Deal(title="Javaエンジニア案件 東京 リモート可", skills_json=json.dumps(["Java", "Spring Boot"]), location="東京")
    deal_c = Deal(title="デザイナー募集 大阪", skills_json=json.dumps(["Figma"]), location="大阪")
    db_session.add_all([deal_a, deal_b, deal_c])
    db_session.commit()

    matches = await find_duplicate_deals(db_session, deal_a, verify_with_llm=False)
    matched_ids = {m.other_id for m in matches}

    assert deal_b.id in matched_ids
    assert deal_c.id not in matched_ids
    assert all(m.relation == "candidate" for m in matches)
