"""Zero-dependency, zero-network provider.

This is what the app runs on when AI is disabled (`ai_enabled=false`), when
no provider is configured yet (first run), and it's also what
`services/fallback_classifier.py` reaches for when a real provider raises
`LLMProviderError` — so a live API outage degrades the product to "simple
keyword rules" instead of breaking mail entirely.

It is deliberately simple: keyword matching against the taxonomy in
app.schemas.classification.DEFAULT_CATEGORIES. It is NOT meant to be
accurate; it exists so the pipeline always has *something* to return.
"""
from __future__ import annotations

from app.providers.llm.base import LLMProvider, LLMResponse

_KEYWORD_RULES: list[tuple[str, float, list[str]]] = [
    # 人材紹介 gets a higher base confidence than 案件紹介: a real user
    # report showed a skill-sheet-attached mail landing in 案件 because
    # both categories matched with the same flat confidence and
    # top_category() (max-by-confidence) fell back to whichever came first
    # in this list. "スキルシートが添付、もしくは人間のスキルが本文に書い
    # てあるものは案件ではなく人材" — these keywords (plus the attachment
    # excerpt text build_context() appends, which includes the file's own
    # 経歴書/職務経歴 wording) are a stronger, more specific signal than a
    # generic "案件のご紹介" phrase, which can appear in candidate-related
    # mail too (e.g. a reply quoting "ご案件をご紹介いただき...").
    (
        "人材紹介",
        0.8,
        [
            "人材のご紹介",
            "エンジニアのご紹介",
            "要員のご紹介",
            "スキルシート",
            "経歴書",
            "職務経歴",
            # A real user-reported miss: a candidate-profile mail (his
            # skills/experience spelled out under a "■氏名"-style block)
            # matched none of the phrases above, so it fell through to
            # 案件紹介 purely because the mail also says "案件をご紹介
            # いただく際には". These markers are how SES 人材紹介 mail
            # actually introduces a specific technician in practice.
            "技術者情報",
            "■氏名",
            "要員情報",
        ],
    ),
    ("案件紹介", 0.65, ["案件のご紹介", "案件情報", "募集案件", "案件をご紹介"]),
    ("日程調整", 0.6, ["日程調整", "打ち合わせ", "面談日程", "候補日"]),
    ("契約", 0.6, ["契約書", "発注書", "基本契約", "ご契約"]),
    ("請求", 0.6, ["請求書", "ご請求", "お振込み", "支払い"]),
    ("障害通知", 0.6, ["障害", "メンテナンス", "サービス停止"]),
    ("広告", 0.55, ["メルマガ", "配信停止", "セミナーのご案内"]),
    ("迷惑メール", 0.55, ["当選しました", "至急ご確認", "副業で稼ぐ"]),
]

_REPLY_HINTS = ["ご返信", "お返事", "ご回答ください", "至急", "至急ご確認"]


class LocalMockProvider(LLMProvider):
    name = "local_mock"

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict, LLMResponse]:
        # This provider is the default for *every* JSON-producing task (not
        # just classification) — duplicate_detection_service and
        # matching_service also call get_llm_provider() and land here when
        # no real API key is configured. Returning the classification shape
        # unconditionally used to leak classification-flavored "rationale"
        # text into duplicate/match results; dispatch on which system
        # prompt is asking so each task gets a shape its caller actually
        # expects (see each service's DEFAULT_SYSTEM_PROMPT for the marker
        # strings matched below).
        if "統合解析タスク" in system_prompt:
            result = {"classification": self._classification_stub(user_prompt), "extraction": {}}
        elif "重複か判定" in system_prompt:
            result = self._duplicate_stub()
        elif "マッチングアドバイザー" in system_prompt:
            result = self._matching_stub()
        elif "構造化データを抽出" in system_prompt:
            result = {}  # no offline heuristic for extraction; an empty result is a safe, honest default
        else:
            result = self._classification_stub(user_prompt)
        return result, LLMResponse(text=str(result), model=self.name)

    async def complete_text(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        return LLMResponse(
            text="[オフラインモード] AIプロバイダーが設定されていないため、テンプレート応答のみ生成できます。",
            model=self.name,
        )

    def _classification_stub(self, text: str) -> dict:
        scored = [(label, confidence) for label, confidence, keywords in _KEYWORD_RULES if any(k in text for k in keywords)]
        if not scored:
            scored = [("その他", 0.5)]
        matched = [label for label, _confidence in scored]
        # max() ties break on first-seen, so mail_type used to always land
        # on whichever category happened to be declared first in
        # _KEYWORD_RULES whenever two categories matched — picking by each
        # rule's own confidence instead means the more specific signal
        # (e.g. 人材紹介's スキルシート) actually wins.
        top_label = max(scored, key=lambda pair: pair[1])[0]
        reply_required = any(hint in text for hint in _REPLY_HINTS)

        return {
            "mail_type": top_label,
            "categories": [{"label": label, "confidence": confidence} for label, confidence in scored],
            "priority": "high" if reply_required else "normal",
            "reply_required": reply_required,
            "reply_deadline": None,
            "action_items": [],
            "important_keywords": [],
            "risk_keywords": [],
            "negative_factors": [],
            "urgency": "high" if reply_required else "normal",
            "sentiment": "neutral",
            "temperature": "warm",
            "tags": matched,
            "rationale": (
                "オフラインのキーワード一致ルールで分類しました"
                f"（一致キーワードに基づき {', '.join(matched)} と判定）。"
                " 実際のAIプロバイダーが利用可能になると、より精緻な分類に置き換わります。"
            ),
        }

    def _duplicate_stub(self) -> dict:
        return {
            "relation": "candidate",
            "reason": "オフラインモードのため埋め込み類似度のみに基づく重複候補として扱っています。",
        }

    def _matching_stub(self) -> dict:
        # No "score" key: callers (matching_service._score_with_llm) fall
        # back to the raw embedding similarity when it's absent.
        return {"rationale": "オフラインモードのため埋め込み類似度のみに基づく推定スコアです。"}
