"""メール横断検索: plain substring search today (works with zero setup on
SQLite), with the seams DESIGN.md section 2.4/2.5 calls for already in
place:
  - `FullTextSearchBackend` -> swap SqliteLikeBackend for a real FTS5
    virtual-table backend or Meilisearch without touching callers.
  - `natural_language_search` -> today it heuristically maps a query like
    "React案件で単価80万以上" onto AIAnalysis JSON fields; Phase 2 replaces
    the heuristic with an LLM-generated filter (function-calling) and adds
    the Chroma/pgvector vector search leg.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.db.models.ai import AIAnalysis
from app.db.models.email import Message


class FullTextSearchBackend(ABC):
    @abstractmethod
    def search(self, db: Session, query: str, limit: int = 50) -> list[Message]: ...


class SqliteLikeBackend(FullTextSearchBackend):
    """LIKE-based search. Adequate for the scaffold; swap for a real FTS5
    virtual table (`CREATE VIRTUAL TABLE messages_fts USING fts5(...)`) once
    mail volume makes LIKE scans too slow (see DESIGN.md 2.4)."""

    def search(self, db: Session, query: str, limit: int = 50) -> list[Message]:
        like = f"%{query}%"
        return (
            db.query(Message)
            .filter((Message.subject.like(like)) | (Message.body_text.like(like)))
            .order_by(Message.received_at.desc())
            .limit(limit)
            .all()
        )


_PRICE_RE = re.compile(r"単価\s*(\d+)\s*万")


def natural_language_search(db: Session, query: str, limit: int = 50) -> list[Message]:
    """Very small heuristic NL->filter mapper covering the spec's own
    examples ("React案件で単価80万以上"). This is intentionally simple; a
    real implementation should have the LLM emit a structured filter via
    function-calling against ClassificationResult/ExtractionResult fields.
    """
    min_price_match = _PRICE_RE.search(query)
    keyword = _PRICE_RE.sub("", query)
    keyword = keyword.replace("案件で", "").replace("単価", "").replace("以上", "").strip()

    q = db.query(Message).join(AIAnalysis, AIAnalysis.message_id == Message.id, isouter=True)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((Message.subject.like(like)) | (Message.body_text.like(like)))

    results = q.order_by(Message.received_at.desc()).limit(limit * 3).all()

    if min_price_match:
        threshold = int(min_price_match.group(1))
        filtered = []
        for message in results:
            analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
            if not analysis or not analysis.extraction_json:
                continue
            extraction = json.loads(analysis.extraction_json)
            price_text = extraction.get("unit_price") or ""
            price_numbers = [int(n) for n in re.findall(r"\d+", price_text)]
            if any(n >= threshold for n in price_numbers):
                filtered.append(message)
        results = filtered

    return results[:limit]
