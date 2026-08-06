"""Structured filter a natural-language search query gets translated into
(see services/search_service.ai_search). extra="allow" for the same reason
as classification/extraction: a prompt author can add a field later without
a code change dropping it silently."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SearchFilter(BaseModel):
    model_config = ConfigDict(extra="allow")

    keyword: str | None = None
    mail_type: str | None = None  # one of DEFAULT_CATEGORIES, best-effort match
    min_unit_price: int | None = None  # 万円単位
    reply_required: bool | None = None
