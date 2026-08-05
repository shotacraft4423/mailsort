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

_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    ("案件紹介", ["案件のご紹介", "案件情報", "募集案件", "案件をご紹介"]),
    ("人材紹介", ["人材のご紹介", "エンジニアのご紹介", "要員のご紹介", "スキルシート"]),
    ("日程調整", ["日程調整", "打ち合わせ", "面談日程", "候補日"]),
    ("契約", ["契約書", "発注書", "基本契約", "ご契約"]),
    ("請求", ["請求書", "ご請求", "お振込み", "支払い"]),
    ("障害通知", ["障害", "メンテナンス", "サービス停止"]),
    ("広告", ["メルマガ", "配信停止", "セミナーのご案内"]),
    ("迷惑メール", ["当選しました", "至急ご確認", "副業で稼ぐ"]),
]

_REPLY_HINTS = ["ご返信", "お返事", "ご回答ください", "至急", "至急ご確認"]


class LocalMockProvider(LLMProvider):
    name = "local_mock"

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> tuple[dict, LLMResponse]:
        text = user_prompt
        matched = [label for label, keywords in _KEYWORD_RULES if any(k in text for k in keywords)]
        if not matched:
            matched = ["その他"]

        reply_required = any(hint in text for hint in _REPLY_HINTS)
        result = {
            "mail_type": matched[0],
            "categories": [{"label": label, "confidence": 0.55} for label in matched],
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
        return result, LLMResponse(text=str(result), model=self.name)

    async def complete_text(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        return LLMResponse(
            text="[オフラインモード] AIプロバイダーが設定されていないため、テンプレート応答のみ生成できます。",
            model=self.name,
        )
