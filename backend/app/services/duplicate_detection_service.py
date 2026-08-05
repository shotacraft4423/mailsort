"""AI重複判定: finds Deals (案件) or Candidates (人材) that are likely the
same opportunity/person distributed through different companies.

Two-stage approach per DESIGN.md section 2.6 / spec: cheap embedding cosine
similarity narrows the candidate set, then (optionally) an LLM call decides
whether it's an exact duplicate, a "duplicate candidate" (same opportunity,
different sales channel / price), or genuinely different.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.deal import Candidate, Deal
from app.providers.embedding.registry import get_embedding_provider
from app.providers.llm.base import LLMProviderError
from app.providers.llm.registry import get_llm_provider

DuplicateRelation = Literal["exact", "candidate", "different"]


@dataclass
class DuplicateMatch:
    other_id: str
    similarity: float
    relation: DuplicateRelation
    reason: str


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)


def _deal_fingerprint(deal: Deal) -> str:
    skills = ", ".join(json.loads(deal.skills_json or "[]"))
    return f"{deal.title} {skills} {deal.location or ''} {deal.period or ''}"


def _candidate_fingerprint(candidate: Candidate) -> str:
    skills = ", ".join(json.loads(candidate.skills_json or "[]"))
    return f"{candidate.display_name} {skills} {candidate.location_preference or ''}"


async def find_duplicate_deals(db: Session, deal: Deal, *, verify_with_llm: bool = True) -> list[DuplicateMatch]:
    settings = get_settings()
    candidates = db.query(Deal).filter(Deal.id != deal.id, Deal.status == "open").all()
    if not candidates:
        return []

    embedder = get_embedding_provider()
    texts = [_deal_fingerprint(deal)] + [_deal_fingerprint(c) for c in candidates]
    vectors = await embedder.embed(texts)
    target_vec, other_vecs = vectors[0], vectors[1:]

    above_threshold: list[tuple[Deal, float]] = []
    for other, vec in zip(candidates, other_vecs):
        similarity = cosine_similarity(target_vec, vec)
        if similarity >= settings.duplicate_similarity_threshold:
            above_threshold.append((other, similarity))
    above_threshold.sort(key=lambda pair: pair[1], reverse=True)

    matches: list[DuplicateMatch] = []
    # Embedding similarity is cheap; the LLM verification call is not. Cap
    # it to the strongest N candidates (settings.duplicate_llm_verification_top_n)
    # instead of one call per above-threshold match, which could otherwise
    # scale unboundedly with how many similar deals are on file.
    for rank, (other, similarity) in enumerate(above_threshold):
        if verify_with_llm and rank < settings.duplicate_llm_verification_top_n:
            relation, reason = await _verify_relation(kind="案件", a=_deal_fingerprint(deal), b=_deal_fingerprint(other))
        else:
            relation, reason = "candidate", f"埋め込み類似度 {similarity:.2f} が閾値を超過"

        matches.append(DuplicateMatch(other_id=other.id, similarity=similarity, relation=relation, reason=reason))

    return matches


async def find_duplicate_candidates(
    db: Session, candidate: Candidate, *, verify_with_llm: bool = True
) -> list[DuplicateMatch]:
    settings = get_settings()
    others = db.query(Candidate).filter(Candidate.id != candidate.id, Candidate.status == "open").all()
    if not others:
        return []

    embedder = get_embedding_provider()
    texts = [_candidate_fingerprint(candidate)] + [_candidate_fingerprint(c) for c in others]
    vectors = await embedder.embed(texts)
    target_vec, other_vecs = vectors[0], vectors[1:]

    above_threshold: list[tuple[Candidate, float]] = []
    for other, vec in zip(others, other_vecs):
        similarity = cosine_similarity(target_vec, vec)
        if similarity >= settings.duplicate_similarity_threshold:
            above_threshold.append((other, similarity))
    above_threshold.sort(key=lambda pair: pair[1], reverse=True)

    matches: list[DuplicateMatch] = []
    for rank, (other, similarity) in enumerate(above_threshold):
        if verify_with_llm and rank < settings.duplicate_llm_verification_top_n:
            relation, reason = await _verify_relation(
                kind="人材", a=_candidate_fingerprint(candidate), b=_candidate_fingerprint(other)
            )
        else:
            relation, reason = "candidate", f"埋め込み類似度 {similarity:.2f} が閾値を超過"

        matches.append(DuplicateMatch(other_id=other.id, similarity=similarity, relation=relation, reason=reason))

    return matches


def persist_deal_duplicates(db: Session, deal: Deal, matches: list[DuplicateMatch]) -> None:
    """Writes exact/candidate matches onto Deal.duplicate_of_id so a cluster
    can be queried back later (GET /deals/{id}/network — "重複案件ネットワーク
    表示"). find_duplicate_deals itself stays pure/side-effect-free (it's
    also called ad hoc without wanting to mutate the DB); this is opt-in,
    called from the API route after a search.

    Simplified union: whichever deal already has a cluster (its own id, if
    none) becomes every match's `duplicate_of_id`. A deal that's already
    linked to a different cluster is left alone rather than silently
    reassigned — clusters can undershoot (miss a merge) but never produce a
    contradictory double assignment.
    """
    root_id = deal.duplicate_of_id or deal.id
    linked_any = False
    for match in matches:
        if match.relation not in ("exact", "candidate"):
            continue
        other = db.query(Deal).filter(Deal.id == match.other_id).one_or_none()
        if other is None or other.id == root_id or other.duplicate_of_id is not None:
            continue
        other.duplicate_of_id = root_id
        other.duplicate_relation = match.relation
        linked_any = True
    if linked_any:
        db.commit()


def persist_candidate_duplicates(db: Session, candidate: Candidate, matches: list[DuplicateMatch]) -> None:
    root_id = candidate.duplicate_of_id or candidate.id
    linked_any = False
    for match in matches:
        if match.relation not in ("exact", "candidate"):
            continue
        other = db.query(Candidate).filter(Candidate.id == match.other_id).one_or_none()
        if other is None or other.id == root_id or other.duplicate_of_id is not None:
            continue
        other.duplicate_of_id = root_id
        other.duplicate_relation = match.relation
        linked_any = True
    if linked_any:
        db.commit()


async def _verify_relation(*, kind: str, a: str, b: str) -> tuple[DuplicateRelation, str]:
    """Ask the LLM to distinguish "same opportunity, different sales
    channel/price" (candidate) from "genuinely the same posting" (exact)
    from "coincidentally similar but different" (different). Falls back to
    "candidate" (the conservative default: flag for human review rather
    than silently merging or silently ignoring) if the provider is down.
    """
    system_prompt = (
        f"2件の{kind}情報が同一{kind}の重複か判定してください。"
        "完全一致なら exact、営業担当・商流・単価のみ違う同一案件/人材なら candidate、"
        "無関係なら different を、JSON {\"relation\": ..., \"reason\": ...} で返してください。"
    )
    user_prompt = f"A: {a}\nB: {b}"
    try:
        provider = get_llm_provider()
        raw, _usage = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        relation = raw.get("relation", "candidate")
        if relation not in ("exact", "candidate", "different"):
            relation = "candidate"
        return relation, raw.get("reason", "")
    except LLMProviderError:
        return "candidate", "LLM検証が利用できないため、埋め込み類似度のみに基づく重複候補としています。"
