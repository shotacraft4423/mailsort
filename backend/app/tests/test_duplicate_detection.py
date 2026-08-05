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


@pytest.mark.asyncio
async def test_llm_verification_is_capped_to_top_n_candidates(db_session, monkeypatch):
    """Regression test: LLM verification must not run once per
    above-threshold match — that scales unboundedly with how many similar
    deals are on file. Only the top duplicate_llm_verification_top_n
    candidates by similarity get verified; the rest fall back to the
    similarity-only "candidate" relation."""
    monkeypatch.setenv("MAILSORT_DUPLICATE_SIMILARITY_THRESHOLD", "0.01")
    monkeypatch.setenv("MAILSORT_DUPLICATE_LLM_VERIFICATION_TOP_N", "2")
    from app.core.config import get_settings

    get_settings.cache_clear()

    target = Deal(title="Java案件 東京", skills_json=json.dumps(["Java"]), location="東京")
    others = [Deal(title=f"Java案件 東京 {i}", skills_json=json.dumps(["Java"]), location="東京") for i in range(4)]
    db_session.add_all([target, *others])
    db_session.commit()

    call_count = 0
    from app.services import duplicate_detection_service as svc

    original_verify = svc._verify_relation

    async def counting_verify(**kwargs):
        nonlocal call_count
        call_count += 1
        return await original_verify(**kwargs)

    monkeypatch.setattr(svc, "_verify_relation", counting_verify)

    matches = await find_duplicate_deals(db_session, target, verify_with_llm=True)

    assert len(matches) == 4
    assert call_count == 2
