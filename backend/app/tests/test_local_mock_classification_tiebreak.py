"""Regression coverage for LocalMockProvider._classification_stub: a real
user report showed a skill-sheet-attached mail landing in 案件 because
案件紹介 and 人材紹介 both matched with the same flat 0.55 confidence, and
ClassificationResult.top_category() (max-by-confidence) broke the tie by
picking whichever category was declared first in _KEYWORD_RULES — always
案件紹介. Categories now carry their own base confidence so a more specific
signal (人材紹介's スキルシート) wins outright instead of depending on
declaration order."""
from __future__ import annotations

import pytest

from app.providers.llm.local_mock import LocalMockProvider

_CLASSIFICATION_SYSTEM_PROMPT = "統合解析タスク"


@pytest.mark.asyncio
async def test_skill_sheet_keyword_outranks_deal_keyword_on_the_same_mail():
    provider = LocalMockProvider()
    text = "案件のご紹介です。スキルシートを添付いたします。"

    raw, _usage = await provider.complete_json(system_prompt=_CLASSIFICATION_SYSTEM_PROMPT, user_prompt=text)

    classification = raw["classification"]
    assert classification["mail_type"] == "人材紹介"
    scores = {c["label"]: c["confidence"] for c in classification["categories"]}
    assert scores["人材紹介"] > scores["案件紹介"]


@pytest.mark.asyncio
async def test_deal_only_mail_is_still_classified_as_deal():
    provider = LocalMockProvider()
    text = "案件のご紹介です。ご検討ください。"

    raw, _usage = await provider.complete_json(system_prompt=_CLASSIFICATION_SYSTEM_PROMPT, user_prompt=text)

    assert raw["classification"]["mail_type"] == "案件紹介"
