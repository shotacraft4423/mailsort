"""メール横断検索: plain substring search today (works with zero setup on
SQLite), with the seams DESIGN.md section 2.4/2.5 calls for already in
place:
  - `FullTextSearchBackend` -> swap SqliteLikeBackend for a real FTS5
    virtual-table backend or Meilisearch without touching callers.
  - `natural_language_search` -> a small regex heuristic mapping a query
    like "React案件で単価80万以上" onto AIAnalysis JSON fields. `ai_search`
    below is the "Phase 2" the old docstring here used to describe as
    future work: it now actually asks the LLM to translate the query into
    a SearchFilter, falling back to this heuristic when AI is off/fails —
    so natural_language_search stays as the always-available offline path.
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models.ai import AIAnalysis
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.registry import get_llm_provider
from app.schemas.search import SearchFilter


class FullTextSearchBackend(ABC):
    @abstractmethod
    def search(
        self, db: Session, query: str, limit: int = 50, *, folder: str | None = None, account_id: str | None = None
    ) -> list[Message]: ...


class SqliteLikeBackend(FullTextSearchBackend):
    """LIKE-based search. Adequate for the scaffold; swap for a real FTS5
    virtual table (`CREATE VIRTUAL TABLE messages_fts USING fts5(...)`) once
    mail volume makes LIKE scans too slow (see DESIGN.md 2.4).

    folder/account_id scope results the same way GET /mail does — without
    this, search always searched every folder in every account, so there
    was no way to "search within 案件" the way you can already filter the
    plain mail list to just that folder."""

    def search(
        self, db: Session, query: str, limit: int = 50, *, folder: str | None = None, account_id: str | None = None
    ) -> list[Message]:
        like = f"%{query}%"
        q = db.query(Message).filter((Message.subject.like(like)) | (Message.body_text.like(like)))
        if folder:
            q = q.filter(Message.folder == folder)
        if account_id:
            q = q.filter(Message.account_id == account_id)
        return q.order_by(Message.received_at.desc()).limit(limit).all()


_PRICE_RE = re.compile(r"単価\s*(\d+)\s*万")


def natural_language_search(
    db: Session, query: str, limit: int = 50, *, folder: str | None = None, account_id: str | None = None
) -> list[Message]:
    """Very small heuristic NL->filter mapper covering the spec's own
    examples ("React案件で単価80万以上"). This is intentionally simple; a
    real implementation should have the LLM emit a structured filter via
    function-calling against ClassificationResult/ExtractionResult fields.

    folder/account_id scope the search the same way plain search does —
    "このフォルダの中で単価80万以上を絞り込みたい" shouldn't require
    scanning every folder in every account first.
    """
    min_price_match = _PRICE_RE.search(query)
    keyword = _PRICE_RE.sub("", query)
    keyword = keyword.replace("案件で", "").replace("単価", "").replace("以上", "").strip()

    q = db.query(Message).join(AIAnalysis, AIAnalysis.message_id == Message.id, isouter=True)
    if folder:
        q = q.filter(Message.folder == folder)
    if account_id:
        q = q.filter(Message.account_id == account_id)
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


_FILTER_SYSTEM_PROMPT = (
    "あなたはメール検索アシスタントです。ユーザーが入力した自由文の検索条件を、"
    '次のJSONスキーマの構造化フィルタに変換してください: '
    '{"keyword": string|null, "mail_type": string|null, "min_unit_price": number|null, "reply_required": boolean|null}\n'
    "- keyword: 件名・本文に含まれるべきキーワード（該当なければnull）\n"
    "- mail_type: 案件紹介/人材紹介/案件返信/人材返信/日程調整/契約/請求/重要/要返信/迷惑メール のいずれか。指定がなければnull\n"
    "- min_unit_price: 単価の下限（万円単位の数値）。指定がなければnull\n"
    "- reply_required: 返信が必要なメールに絞りたい場合はtrue。指定がなければnull\n"
    "JSON以外の文字は一切出力しないでください。"
)


async def ai_search(
    db: Session, query: str, limit: int = 50, *, folder: str | None = None, account_id: str | None = None
) -> list[Message]:
    """"フォルダの中でもプロンプトで絞り込みたい" — asks the configured
    LLM to translate a free-text query ("単価80万以上の案件だけ" etc.) into
    a SearchFilter, then applies it deterministically via SQL/JSON field
    checks (one LLM call per search, not per message — same
    token-efficiency principle as the rest of the pipeline). Falls back to
    the regex-based natural_language_search when AI is off, unconfigured,
    or the call fails for any reason, so search never breaks outright."""
    settings = get_settings()
    if settings.ai_enabled:
        provider = get_llm_provider()
        if provider.name != "local_mock":
            try:
                raw, _usage = await provider.complete_json(system_prompt=_FILTER_SYSTEM_PROMPT, user_prompt=query)
                search_filter = SearchFilter.model_validate(raw)
                return _apply_search_filter(db, search_filter, limit, folder=folder, account_id=account_id)
            except (LLMProviderError, ValidationError):
                pass
    return natural_language_search(db, query, limit, folder=folder, account_id=account_id)


def _apply_search_filter(
    db: Session, filt: SearchFilter, limit: int, *, folder: str | None, account_id: str | None
) -> list[Message]:
    q = db.query(Message)
    if folder:
        q = q.filter(Message.folder == folder)
    if account_id:
        q = q.filter(Message.account_id == account_id)
    if filt.keyword:
        like = f"%{filt.keyword}%"
        q = q.filter((Message.subject.like(like)) | (Message.body_text.like(like)))

    results = q.order_by(Message.received_at.desc()).limit(limit * 3).all()

    needs_analysis_check = filt.mail_type or filt.reply_required is not None or filt.min_unit_price is not None
    if not needs_analysis_check:
        return results[:limit]

    filtered = []
    for message in results:
        analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
        if not analysis:
            continue
        classification = json.loads(analysis.classification_json or "{}")
        if filt.mail_type and classification.get("mail_type") != filt.mail_type:
            continue
        if filt.reply_required is not None and bool(classification.get("reply_required")) != filt.reply_required:
            continue
        if filt.min_unit_price is not None:
            extraction = json.loads(analysis.extraction_json or "{}")
            price_text = extraction.get("unit_price") or ""
            price_numbers = [int(n) for n in re.findall(r"\d+", price_text)]
            if not any(n >= filt.min_unit_price for n in price_numbers):
                continue
        filtered.append(message)

    return filtered[:limit]
