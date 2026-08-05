from __future__ import annotations

import json

import pytest

from app.db.models.deal import Candidate, Deal
from app.services.matching_service import find_matches_for_deal


@pytest.mark.asyncio
async def test_matches_are_persisted_and_ranked(db_session, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("MAILSORT_LLM_PROVIDER", "local_mock")
    get_settings.cache_clear()

    deal = Deal(title="Java案件 東京", skills_json=json.dumps(["Java", "Spring"]), location="東京")
    good_candidate = Candidate(
        display_name="Aさん", skills_json=json.dumps(["Java", "Spring Boot"]), location_preference="東京"
    )
    unrelated_candidate = Candidate(display_name="Bさん", skills_json=json.dumps(["Figma", "デザイン"]), location_preference="大阪")
    db_session.add_all([deal, good_candidate, unrelated_candidate])
    db_session.commit()

    results = await find_matches_for_deal(db_session, deal, top_n=5, verify_with_llm=False)

    assert len(results) == 2
    assert results[0].match.candidate_id == good_candidate.id
    assert results[0].match.score >= results[1].match.score

    from app.db.models.deal import MatchScore

    persisted = db_session.query(MatchScore).filter(MatchScore.deal_id == deal.id).all()
    assert len(persisted) == 2


@pytest.mark.asyncio
async def test_find_matches_for_deal_returns_empty_when_no_candidates(db_session):
    deal = Deal(title="Python案件", skills_json=json.dumps(["Python"]))
    db_session.add(deal)
    db_session.commit()

    results = await find_matches_for_deal(db_session, deal, verify_with_llm=False)
    assert results == []


@pytest.mark.asyncio
async def test_rerunning_matches_updates_rather_than_duplicates(db_session):
    deal = Deal(title="Java案件", skills_json=json.dumps(["Java"]))
    candidate = Candidate(display_name="Aさん", skills_json=json.dumps(["Java"]))
    db_session.add_all([deal, candidate])
    db_session.commit()

    await find_matches_for_deal(db_session, deal, verify_with_llm=False)
    await find_matches_for_deal(db_session, deal, verify_with_llm=False)

    from app.db.models.deal import MatchScore

    persisted = db_session.query(MatchScore).filter(MatchScore.deal_id == deal.id).all()
    assert len(persisted) == 1
