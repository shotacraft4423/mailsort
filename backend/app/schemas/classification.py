"""The AI classification JSON contract.

This is the schema every LLMProvider implementation must (attempt to)
satisfy for the `classify` task. It is intentionally permissive
(`model_config extra="allow"`) so a provider can return categories or
fields the taxonomy doesn't know about yet ("未知カテゴリにも対応できる
柔軟設計") without them being silently dropped — they round-trip through
`model_dump()` and get stored in AIAnalysis.classification_json as-is.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Seed taxonomy from the product spec. This is a *default* vocabulary, not an
# enum constraint — see CategoryTag.label (plain str) below.
DEFAULT_CATEGORIES: list[str] = [
    "案件紹介",
    "人材紹介",
    "案件返信",
    "人材返信",
    "日程調整",
    "契約",
    "請求",
    "営業メール",
    "広告",
    "自動配信",
    "社内",
    "障害通知",
    "重要",
    "要返信",
    "迷惑メール",
    "その他",
]

Priority = Literal["urgent", "high", "normal", "low"]
Temperature = Literal["hot", "warm", "cold"]
Sentiment = Literal["positive", "neutral", "negative"]


class CategoryTag(BaseModel):
    model_config = ConfigDict(extra="allow")

    label: str
    confidence: float = Field(ge=0.0, le=1.0)


class ReplyCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    tone: str  # 丁寧 | 普通 | 営業 | フレンドリー | 断る | 日程調整 | お礼 | 催促 | 確認 | 謝罪 ...
    draft: str


class ClassificationResult(BaseModel):
    """Full output of the "AI分類プロンプト" task — analyzes the whole sales
    email, not a single yes/no question. See DESIGN.md section 5."""

    model_config = ConfigDict(extra="allow")

    mail_type: str  # primary type, usually the top DEFAULT_CATEGORIES entry
    categories: list[CategoryTag] = Field(default_factory=list)  # multi-tag + confidence

    priority: Priority = "normal"
    reply_required: bool = False
    reply_deadline: str | None = None  # ISO date, if inferable
    action_items: list[str] = Field(default_factory=list)

    sales_phase: str | None = None  # 新規/商談中/成約/請求/クローズ 等
    customer: str | None = None
    project_summary: str | None = None  # 案件 요약
    candidate_summary: str | None = None  # 人材 요약
    meeting_related: bool = False
    contract_related: bool = False
    billing_related: bool = False

    important_keywords: list[str] = Field(default_factory=list)
    risk_keywords: list[str] = Field(default_factory=list)  # 危険ワード (クレーム, 契約解除, 訴訟 等)
    sales_opportunity: str | None = None  # 営業機会の説明
    negative_factors: list[str] = Field(default_factory=list)
    urgency: Priority = "normal"
    sentiment: Sentiment = "neutral"
    temperature: Temperature = "warm"

    attachment_analysis_notes: str | None = None
    thread_analysis_notes: str | None = None
    reply_candidates: list[ReplyCandidate] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)
    rationale: str = ""  # human-readable "why" — feeds AuditLogEntry.rationale

    def top_category(self) -> str | None:
        if not self.categories:
            return None
        return max(self.categories, key=lambda c: c.confidence).label
