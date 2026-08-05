"""案件・人材マッチングスコア: given a Deal, find the best-fitting Candidates
in the bench (or vice versa) and estimate a success likelihood score.

Shares the two-stage pattern from duplicate_detection_service.py (cheap
embedding similarity narrows the field, then an optional LLM call turns
"these look similar" into "here's why this candidate suits this deal, and
how confident to be") — see that module's docstring for why that split
makes sense cost/latency-wise. The two use cases are semantically
different, though: duplicate detection asks "are these the same thing?"
while matching asks "how well do these two different things fit together?",
so it stays a separate module rather than a shared code path.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models.deal import Candidate, Deal, MatchScore
from app.providers.embedding.registry import get_embedding_provider
from app.providers.llm.base import LLMProviderError
from app.providers.llm.registry import get_llm_provider
from app.services.duplicate_detection_service import cosine_similarity


def _deal_text(deal: Deal) -> str:
    skills = ", ".join(json.loads(deal.skills_json or "[]"))
    return f"案件: {deal.title} / スキル: {skills} / 勤務地: {deal.location or ''} / 単価: {deal.unit_price_min or '?'}〜{deal.unit_price_max or '?'}万円"


def _candidate_text(candidate: Candidate) -> str:
    skills = ", ".join(json.loads(candidate.skills_json or "[]"))
    return (
        f"人材: {candidate.display_name} / スキル: {skills} / "
        f"希望勤務地: {candidate.location_preference or ''} / 単価: {candidate.unit_price_min or '?'}〜{candidate.unit_price_max or '?'}万円"
    )


@dataclass
class MatchCandidate:
    match: MatchScore
    similarity: float


async def _score_with_llm(*, deal_text: str, candidate_text: str, similarity: float) -> tuple[float, str]:
    """Refines the raw embedding similarity into a 0-1 success-likelihood
    score with a human-readable rationale. Falls back to the raw
    similarity (clamped) when the LLM is unavailable — a worse estimate,
    but never a hard failure, consistent with the rest of the AI pipeline's
    "degrade, don't break" policy."""
    system_prompt = (
        "あなたはSES営業のマッチングアドバイザーです。案件と人材の情報から、"
        "成約可能性を0.0〜1.0のスコアと日本語の一言理由でJSON "
        '{"score": 0.0, "rationale": "..."} 形式で返してください。'
        "スキル適合度・単価適合度・勤務地適合度を総合的に考慮してください。"
    )
    user_prompt = f"{deal_text}\n{candidate_text}\n(参考: 埋め込み類似度 {similarity:.2f})"
    try:
        provider = get_llm_provider()
        raw, _usage = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        score = float(raw.get("score", similarity))
        score = max(0.0, min(1.0, score))
        return score, str(raw.get("rationale", ""))
    except (LLMProviderError, TypeError, ValueError):
        return max(0.0, min(1.0, similarity)), "埋め込み類似度のみに基づく推定スコアです（LLM評価は利用できませんでした）。"


def _upsert_match(db: Session, *, deal_id: str, candidate_id: str, score: float, rationale: str) -> MatchScore:
    existing = (
        db.query(MatchScore).filter(MatchScore.deal_id == deal_id, MatchScore.candidate_id == candidate_id).one_or_none()
    )
    if existing:
        existing.score = score
        existing.rationale = rationale
        return existing
    match = MatchScore(deal_id=deal_id, candidate_id=candidate_id, score=score, rationale=rationale)
    db.add(match)
    return match


async def find_matches_for_deal(
    db: Session, deal: Deal, *, top_n: int = 5, verify_with_llm: bool = True
) -> list[MatchCandidate]:
    candidates = db.query(Candidate).filter(Candidate.status == "open").all()
    if not candidates:
        return []

    embedder = get_embedding_provider()
    deal_text = _deal_text(deal)
    texts = [deal_text] + [_candidate_text(c) for c in candidates]
    vectors = await embedder.embed(texts)
    deal_vec, candidate_vecs = vectors[0], vectors[1:]

    scored: list[tuple[Candidate, float]] = [
        (c, cosine_similarity(deal_vec, vec)) for c, vec in zip(candidates, candidate_vecs)
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    top = scored[:top_n]

    results: list[MatchCandidate] = []
    for candidate, similarity in top:
        if verify_with_llm:
            score, rationale = await _score_with_llm(
                deal_text=deal_text, candidate_text=_candidate_text(candidate), similarity=similarity
            )
        else:
            score, rationale = similarity, "埋め込み類似度に基づく簡易スコアです。"
        match = _upsert_match(db, deal_id=deal.id, candidate_id=candidate.id, score=score, rationale=rationale)
        results.append(MatchCandidate(match=match, similarity=similarity))

    db.commit()
    results.sort(key=lambda r: r.match.score, reverse=True)
    return results


async def find_matches_for_candidate(
    db: Session, candidate: Candidate, *, top_n: int = 5, verify_with_llm: bool = True
) -> list[MatchCandidate]:
    deals = db.query(Deal).filter(Deal.status == "open").all()
    if not deals:
        return []

    embedder = get_embedding_provider()
    candidate_text = _candidate_text(candidate)
    texts = [candidate_text] + [_deal_text(d) for d in deals]
    vectors = await embedder.embed(texts)
    candidate_vec, deal_vecs = vectors[0], vectors[1:]

    scored: list[tuple[Deal, float]] = [(d, cosine_similarity(candidate_vec, vec)) for d, vec in zip(deals, deal_vecs)]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    top = scored[:top_n]

    results: list[MatchCandidate] = []
    for deal, similarity in top:
        if verify_with_llm:
            score, rationale = await _score_with_llm(
                deal_text=_deal_text(deal), candidate_text=candidate_text, similarity=similarity
            )
        else:
            score, rationale = similarity, "埋め込み類似度に基づく簡易スコアです。"
        match = _upsert_match(db, deal_id=deal.id, candidate_id=candidate.id, score=score, rationale=rationale)
        results.append(MatchCandidate(match=match, similarity=similarity))

    db.commit()
    results.sort(key=lambda r: r.match.score, reverse=True)
    return results
