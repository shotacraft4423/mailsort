"""Runs the "AI分類プロンプト" task for a Message and persists an AIAnalysis
row. This is the module that implements the non-functional requirement
"AI機能を無効化しても通常のメーラーとして利用できる" / "API障害時でも通常の
メーラーとして使用可能": any LLMProviderError from the configured provider
is caught and we retry once against LocalMockProvider, tagging the result
`is_fallback=True` so the UI can show "オフライン分類" instead of pretending
it's a full AI result.

A real provider returning syntactically valid JSON that doesn't match
ClassificationResult's shape (missing required `mail_type`, wrong type for
a field, etc. — response_format=json_object only guarantees valid JSON,
not a matching schema) is just as much a "the AI didn't give us something
usable" case as a network error, so pydantic's ValidationError is caught
alongside LLMProviderError and triggers the same offline fallback instead
of bubbling up as an unhandled 500 (which is what "AI分類に失敗しました"
in the UI used to mean before this fix).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import content_hash, mask_text
from app.db.models.ai import AIAnalysis, AuditLogEntry
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.local_mock import LocalMockProvider
from app.providers.llm.registry import get_llm_provider
from app.schemas.classification import CategoryTag, ClassificationResult, ReplyCandidate
from app.services.feedback_service import build_few_shot_suffix, get_similar_corrections
from app.services.prompt_service import get_active_prompt, render_template, truncate_for_ai

logger = logging.getLogger(__name__)

TASK = "classification"

DEFAULT_SYSTEM_PROMPT = (
    "あなたはSES営業向けメールアシスタントです。営業メール全体を解析し、"
    "単純な『案件か人材か』ではなく、優先度・返信要否・期限・アクション・"
    "営業フェーズ・重要ワード・危険ワード・営業機会・ネガティブ要素・緊急度・"
    "感情・温度感まで含めて判定し、指定されたJSONスキーマで返答してください。"
    "未知のカテゴリが妥当な場合は、既存の分類に加えて自由に追加してください。\n\n"
    "【案件紹介 と 人材紹介 の判別基準】\n"
    "添付ファイルがスキルシート・経歴書・職務経歴書である、または本文に"
    "特定の技術者個人のスキル・経験・稼働状況が記載されている場合は、"
    "その技術者を紹介するメールなので『人材紹介』としてください"
    "（案件の詳細も併記されていても、主題が技術者個人の紹介であれば人材紹介です）。"
    "逆に、募集中の案件（業務内容・単価・勤務地・商流など）を紹介し、"
    "技術者個人の情報を伴わない場合は『案件紹介』としてください。\n\n"
    "【reply_required（返信要否）の判定基準】\n"
    "送信者が明確に返答・確認・日程回答・可否連絡を求めている場合、"
    "または期限付きで反応を求めている場合は true にしてください。"
    "単なる情報共有・広告配信・システム通知・お礼メール・完了報告など、"
    "こちらからの返信が本質的に不要なものは false としてください。"
)

DEFAULT_USER_PROMPT_TEMPLATE = (
    "件名: {{ subject }}\n"
    "送信元: {{ sender_name }} <{{ sender_address }}>\n"
    "CC: {{ cc_addresses }}\n"
    "署名: {{ signature_text }}\n"
    "添付ファイル名: {{ attachment_names }}\n"
    "本文:\n{{ body }}{{ attachment_excerpts }}"
)


@dataclass
class ClassificationOutcome:
    analysis: AIAnalysis
    result: ClassificationResult
    from_cache: bool


# "そもそも日本語と英語で求めているvalueの対応を用意したほうが確実じゃない
# かな" — prompt instructions alone are advisory; the model can still write
# "低" instead of "low" for a Literal field despite being told the exact
# allowed values (round 2 of the real fallback bug, after round 1's key-name
# fix: right keys, wrong values — priority="低", temperature="冷たい",
# sentiment="中立"). This is a deterministic normalization pass applied to
# every real response *before* validation, so a known Japanese synonym gets
# coerced to the literal the schema actually requires instead of just
# hoping the model complies. Falls through unchanged (and still validated
# normally) for anything not in the table, so it never masks a genuinely
# new kind of drift — it only fixes the specific aliases seen in practice.
_ENUM_VALUE_ALIASES: dict[str, str] = {
    # Priority (priority / urgency fields): urgent / high / normal / low
    "緊急": "urgent",
    "至急": "urgent",
    "急ぎ": "urgent",
    "高": "high",
    "高い": "high",
    "中": "normal",
    "普通": "normal",
    "通常": "normal",
    "中程度": "normal",
    "低": "low",
    "低い": "low",
    # Sentiment: positive / neutral / negative
    "ポジティブ": "positive",
    "肯定的": "positive",
    "好意的": "positive",
    "中立": "neutral",
    "ニュートラル": "neutral",
    "ネガティブ": "negative",
    "否定的": "negative",
    # Temperature: hot / warm / cold
    "熱い": "hot",
    "ホット": "hot",
    "温かい": "warm",
    "暖かい": "warm",
    "ウォーム": "warm",
    "冷たい": "cold",
    "コールド": "cold",
}

# Required boolean fields (default False, not Optional) that a real model
# sometimes omits or sends as null instead of an explicit true/false.
_REQUIRED_BOOLEAN_FIELDS = ("reply_required", "meeting_related", "contract_related", "billing_related")

# Round 3 of the same bug class: right keys, right (or coerced) enum
# values, but categories came back as a flat list of strings —
# ["案件紹介"] / ["SES", "エンジニア募集"] — instead of
# [{"label": "...", "confidence": 0.8}], because "categories" reads to a
# model like a plain tag list unless the example it's shown demonstrates
# the nested shape (fixed in _required_json_key_instruction below too).
# Rather than patch this one field and wait for the next structural
# variant, this coerces *any* list[BaseModel]-typed field generically:
# bare strings become {<primary field>: value, ...sensible defaults},
# dicts with a plausible alternate key name (category/name/score/...) get
# remapped, and a lone scalar sent instead of a list gets wrapped in one.
# Already-well-formed input passes through untouched either way.
_NESTED_LIST_FIELD_SPECS: dict[str, tuple[type, dict[str, object]]] = {
    # field name -> (pydantic model, {key_aliases_and_defaults})
    "categories": (CategoryTag, {"label": ("category", "name", "type"), "confidence": ("score", "probability", "value")}),
    "reply_candidates": (ReplyCandidate, {"tone": ("style",), "draft": ("text", "content", "body")}),
}
_NESTED_LIST_DEFAULTS: dict[str, dict[str, object]] = {
    "categories": {"confidence": 0.6},
    "reply_candidates": {"draft": ""},
}


def _coerce_nested_list_field(field_name: str, value: object) -> object:
    model_cls, key_aliases = _NESTED_LIST_FIELD_SPECS[field_name]
    defaults = _NESTED_LIST_DEFAULTS.get(field_name, {})
    primary_field = next(iter(model_cls.model_fields))

    if isinstance(value, (str, dict)):
        value = [value]
    if not isinstance(value, list):
        return value

    coerced = []
    for item in value:
        if isinstance(item, str):
            coerced.append({primary_field: item, **defaults})
        elif isinstance(item, dict):
            remapped = dict(item)
            for canonical, aliases in key_aliases.items():
                if canonical in remapped:
                    continue
                for alias in aliases:
                    if alias in remapped:
                        remapped[canonical] = remapped.pop(alias)
                        break
            for key, default_value in defaults.items():
                remapped.setdefault(key, default_value)
            coerced.append(remapped)
        else:
            coerced.append(item)
    return coerced


def normalize_classification_payload(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return raw

    normalized = dict(raw)
    schema = ClassificationResult.model_json_schema()
    for field_name, prop in schema.get("properties", {}).items():
        allowed = prop.get("enum")
        if not allowed:
            continue
        value = normalized.get(field_name)
        if isinstance(value, str) and value not in allowed:
            mapped = _ENUM_VALUE_ALIASES.get(value)
            if mapped in allowed:
                normalized[field_name] = mapped

    for field_name in _NESTED_LIST_FIELD_SPECS:
        if field_name in normalized:
            normalized[field_name] = _coerce_nested_list_field(field_name, normalized[field_name])

    for field_name in _REQUIRED_BOOLEAN_FIELDS:
        if normalized.get(field_name) is None:
            normalized[field_name] = False

    # sales_opportunity is str | None — a model that treats it as a yes/no
    # question sometimes sends a bare boolean instead of a description.
    if isinstance(normalized.get("sales_opportunity"), bool):
        normalized["sales_opportunity"] = None

    return normalized


def build_context(message: Message, *, anonymize: bool) -> dict[str, str]:
    """Shared by classification_service and analysis_service (the combined
    classify+extract call) so both send an identically-truncated body —
    see Settings.max_body_chars_for_ai / max_attachment_excerpt_chars."""
    settings = get_settings()
    body = message.body_text or ""
    if anonymize:
        body = mask_text(body)
    body = truncate_for_ai(body, settings.max_body_chars_for_ai)

    excerpts = []
    for attachment in message.attachments:
        if not attachment.extracted_text:
            continue
        snippet = truncate_for_ai(attachment.extracted_text, settings.max_attachment_excerpt_chars)
        if anonymize:
            snippet = mask_text(snippet)
        excerpts.append(f"\n添付ファイル「{attachment.file_name}」({attachment.classified_kind or '種別不明'})の抜粋:\n{snippet}")

    return {
        "subject": message.subject,
        "sender_name": message.sender_name,
        "sender_address": message.sender_address,
        "cc_addresses": message.cc_addresses,
        "signature_text": message.signature_text,
        "attachment_names": ", ".join(a.file_name for a in message.attachments),
        "body": body,
        "attachment_excerpts": "".join(excerpts),
    }


def _required_json_key_instruction() -> str:
    """Round 1 of this bug (key names translated to Japanese, e.g.
    「案件か人材か」 instead of mail_type) got fixed by listing field names.
    Round 2 was right key names, wrong *values* — priority="低" instead of
    "low", temperature="冷たい" instead of "cold". Round 3 was right keys
    and values but the wrong *shape* for categories — ["案件紹介"] instead
    of [{"label": "案件紹介", "confidence": 0.8}] — because an empty-list
    example (the previous version of this function always built the
    example with no categories set) never actually showed what one entry
    looks like. The example below now includes one populated entry for
    every list[object] field, and normalize_classification_payload is the
    deterministic backstop for whatever the next drift turns out to be —
    this function's job is to make that next round less likely, not to be
    the only line of defense."""
    example = ClassificationResult(
        mail_type="（実際の分類名。以下は例です）",
        categories=[CategoryTag(label="案件紹介", confidence=0.8)],
        reply_candidates=[ReplyCandidate(tone="丁寧", draft="（返信文の例）")],
    ).model_dump()
    schema = ClassificationResult.model_json_schema()
    enum_lines = "\n".join(
        f"- {name}: {' / '.join(prop['enum'])} のいずれか（日本語や他の表現に言い換えないこと）"
        for name, prop in schema.get("properties", {}).items()
        if "enum" in prop
    )
    return (
        "重要: JSONのキー名は必ず以下の英語のフィールド名をそのまま使用してください。"
        "日本語に意訳したキー名や独自のキー名を作ってはいけません。\n"
        f"使うキー名: {', '.join(ClassificationResult.model_fields.keys())}\n"
        "mail_type は必須項目です。既存のカテゴリに当てはまらない場合も、"
        "最も近いカテゴリ名（または「その他」）を必ず文字列で設定してください。\n"
        "categories と reply_candidates は文字列の配列ではなく、"
        "必ず下記の例のようにオブジェクトの配列にしてください。\n"
        "真偽値のフィールド（meeting_related等）は必ず true か false にしてください（nullにしない）。\n"
        f"以下の項目は必ず指定された値のいずれかにしてください:\n{enum_lines}\n"
        "出力フォーマットの例（キー名・型・ネスト構造のみ参考にしてください。値は実際の内容に置き換えます）:\n"
        f"{json.dumps(example, ensure_ascii=False)}"
    )


async def classify_message(db: Session, message: Message, *, force: bool = False) -> ClassificationOutcome:
    settings = get_settings()
    hash_input = content_hash(
        message.subject,
        message.body_text,
        ",".join(sorted(a.file_name for a in message.attachments)),
    )

    existing = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
    if existing and existing.content_hash == hash_input and not force:
        return ClassificationOutcome(
            analysis=existing,
            result=ClassificationResult.model_validate(json.loads(existing.classification_json)),
            from_cache=True,
        )

    active_prompt = get_active_prompt(db, TASK)
    system_prompt = (active_prompt.system_prompt if active_prompt else DEFAULT_SYSTEM_PROMPT) + "\n\n" + _required_json_key_instruction()
    user_template = active_prompt.user_prompt_template if active_prompt else DEFAULT_USER_PROMPT_TEMPLATE
    context = build_context(message, anonymize=settings.anonymize_before_send)
    user_prompt = render_template(user_template, context)
    user_prompt += build_few_shot_suffix(await get_similar_corrections(db, message))

    provider = get_llm_provider()
    is_fallback = False
    fallback_reason: str | None = None

    try:
        raw, _usage = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        result = ClassificationResult.model_validate(normalize_classification_payload(raw))
    except (LLMProviderError, ValidationError) as exc:
        # Previously discarded entirely — "every mail is being classified
        # by the offline fallback" was undiagnosable from inside the app
        # (no error, no log, nothing). Logging it server-side covers anyone
        # watching the process console; storing it on the row is what lets
        # the UI show *why* next to the fallback badge (bad/expired key,
        # rate limit, timeout, quota exhausted, unexpected response shape).
        logger.warning("classification: %s failed (%s), falling back to local_mock", provider.name, exc)
        fallback_reason = str(exc)
        provider = LocalMockProvider()
        is_fallback = True
        raw, _usage = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
        result = ClassificationResult.model_validate(raw)

    if existing:
        analysis = existing
    else:
        analysis = AIAnalysis(message_id=message.id)
        db.add(analysis)

    analysis.content_hash = hash_input
    analysis.provider_used = provider.name
    analysis.prompt_template_id = active_prompt.template_id if active_prompt else None
    analysis.classification_json = json.dumps(result.model_dump(), ensure_ascii=False)
    analysis.is_fallback = is_fallback
    analysis.fallback_reason = fallback_reason
    db.flush()

    db.add(
        AuditLogEntry(
            message_id=message.id,
            action="classify",
            provider_used=provider.name,
            rationale=result.rationale or "根拠は返却されませんでした。",
            data_sent_summary="件名/送信元/CC/署名/添付ファイル名/本文" + ("（匿名化済み）" if settings.anonymize_before_send else ""),
            anonymized=settings.anonymize_before_send,
        )
    )
    db.commit()

    return ClassificationOutcome(analysis=analysis, result=result, from_cache=False)
