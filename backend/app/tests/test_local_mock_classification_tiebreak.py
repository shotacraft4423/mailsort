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


@pytest.mark.asyncio
async def test_real_world_candidate_profile_mail_is_not_misread_as_a_deal():
    """A real user-supplied sample: a technician-introduction mail with no
    literal "人材のご紹介"/"スキルシート" phrase, but also mentioning
    "案件をご紹介いただく際には" (asking the reader to reply with matching
    案件) — which alone used to make this match only the 案件紹介 bucket."""
    provider = LocalMockProvider()
    text = (
        "SES営業ご担当者様\n\nお世話になっております。\n株式会社D-code 平野でございます。\n\n"
        "技術者情報を送付いたします。\n見合う案件がございましたら、ご紹介いただけますと幸いです。\n\n"
        "---------------\n"
        "■氏　名：HY（男性/61歳）\n■最　寄：大泉学園駅\n■所　属：弊社個人事業主\n■稼　動：即日～\n■単　金：68万円\n\n"
        "■スキル：\n富士通系ホスト環境を中心に、インフラ構築・運用保守・更改対応に長年従事。\n"
        "---------------\n\n"
        "案件をご紹介いただく際には、\n・商流\n・精算幅\n・支払いサイト\n"
        "上記をご教示いただけると確認がとりやすいため、よろしくお願いいたします。"
    )

    raw, _usage = await provider.complete_json(system_prompt=_CLASSIFICATION_SYSTEM_PROMPT, user_prompt=text)

    assert raw["classification"]["mail_type"] == "人材紹介"
