"""AI抽出 JSON contract: structured fields pulled out of a message body.

Like ClassificationResult, this is `extra="allow"` so new fields a prompt
author adds later (via the prompt editor) don't need a code change to be
preserved end-to-end.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MeetingInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    platform: str | None = None  # teams | zoom | meet | other
    url: str | None = None
    datetime_text: str | None = None  # raw text as found; parsed downstream
    participants: list[str] = Field(default_factory=list)


class ToolLinks(BaseModel):
    """One field per tool explicitly named in the spec so the UI can render
    dedicated icons/quick-actions instead of a generic link list."""

    model_config = ConfigDict(extra="allow")

    teams: list[str] = Field(default_factory=list)
    meet: list[str] = Field(default_factory=list)
    zoom: list[str] = Field(default_factory=list)
    chatwork: list[str] = Field(default_factory=list)
    slack: list[str] = Field(default_factory=list)
    backlog: list[str] = Field(default_factory=list)
    notion: list[str] = Field(default_factory=list)
    github: list[str] = Field(default_factory=list)
    jira: list[str] = Field(default_factory=list)
    redmine: list[str] = Field(default_factory=list)
    other_urls: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    company_name: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    address: str | None = None

    project_name: str | None = None  # 案件名
    candidate_name: str | None = None  # 人材名 (often anonymized, e.g. "Aさん")
    unit_price: str | None = None  # free text, e.g. "60〜70万円/月"
    location: str | None = None
    skills: list[str] = Field(default_factory=list)
    period: str | None = None
    headcount: int | None = None  # 募集人数
    business_flow: str | None = None  # 商流
    work_style: str | None = None  # 勤務形態
    foreign_nationality_ok: bool | None = None  # 外国籍可否
    age: str | None = None
    interview_count: int | None = None  # 面談回数
    remarks: str | None = None  # 備考

    deadline: str | None = None
    reply_deadline: str | None = None

    meeting: MeetingInfo | None = None
    tool_links: ToolLinks = Field(default_factory=ToolLinks)

    invoice_number: str | None = None
    order_number: str | None = None

    attachments_mentioned: list[str] = Field(default_factory=list)
    todo: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    reply_content_summary: str | None = None
    unanswered_items: list[str] = Field(default_factory=list)
