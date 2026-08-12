"""AI学習モード: users correcting "これは案件" / "これは人材" feed back into
future classification instead of being a one-off UI-only fix.

Design: no fine-tuning, no training job. A correction is stored as
(fingerprint text, corrected label); classification_service/analysis_service
retrieve the most similar past corrections by embedding similarity and
inject them into the prompt as few-shot examples ("this kind of email was
previously misclassified as X, it should have been Y"). This is a modest
accuracy lever, not a real learning system, but it requires zero new
infrastructure and degrades gracefully (no corrections yet → no-op).
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.db.models.ai import AIAnalysis, ClassificationFeedback
from app.db.models.email import Message
from app.providers.embedding.registry import get_embedding_provider
from app.services.duplicate_detection_service import cosine_similarity

FEW_SHOT_TOP_K = 3
# Loose on purpose: these are few-shot hints for the model to weigh, not a
# hard match — unlike duplicate detection there's no wrong answer from
# including a so-so example, just a slightly less useful one.
FEW_SHOT_SIMILARITY_THRESHOLD = 0.3


def _fingerprint(message: Message) -> str:
    return f"{message.subject} {(message.body_text or '')[:300]}"


def record_correction(db: Session, message: Message, corrected_mail_type: str, *, note: str = "") -> ClassificationFeedback:
    analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
    original_mail_type: str | None = None
    if analysis and analysis.classification_json:
        try:
            original_mail_type = json.loads(analysis.classification_json).get("mail_type")
        except json.JSONDecodeError:
            pass

    feedback = ClassificationFeedback(
        message_id=message.id,
        fingerprint_text=_fingerprint(message),
        original_mail_type=original_mail_type,
        corrected_mail_type=corrected_mail_type,
        note=note,
    )
    db.add(feedback)

    # Apply the correction immediately so the UI reflects it without
    # waiting for a re-classify — the few-shot injection below is about
    # *future* emails, this fixes the one the user just corrected.
    if analysis and analysis.classification_json:
        data = json.loads(analysis.classification_json)
        data["mail_type"] = corrected_mail_type
        categories = [c for c in data.get("categories", []) if c.get("label") != corrected_mail_type]
        categories.insert(0, {"label": corrected_mail_type, "confidence": 1.0})
        data["categories"] = categories
        correction_note = f"\n[ユーザー修正] 「{original_mail_type or '未分類'}」から「{corrected_mail_type}」に修正されました。"
        data["rationale"] = (data.get("rationale") or "") + correction_note
        analysis.classification_json = json.dumps(data, ensure_ascii=False)

    db.commit()
    db.refresh(feedback)
    return feedback


def record_reply_not_needed(db: Session, message: Message, *, note: str = "") -> ClassificationFeedback:
    """"返信忘れのところは返信不要ボタンを追加してそれらを学習してください" —
    the dashboard's overdue-reply reminder is driven entirely by
    AIAnalysis.classification_json's reply_required flag (see
    insights_service.compute_reminders). A user marking one as not actually
    needing a reply should (a) drop it off the reminder list immediately,
    same as record_correction() does for mail_type, and (b) become a
    few-shot example so similar future mail is classified reply_required=False
    from the start."""
    analysis = db.query(AIAnalysis).filter(AIAnalysis.message_id == message.id).one_or_none()
    original_reply_required: bool | None = None
    if analysis and analysis.classification_json:
        try:
            original_reply_required = json.loads(analysis.classification_json).get("reply_required")
        except json.JSONDecodeError:
            pass

    feedback = ClassificationFeedback(
        message_id=message.id,
        fingerprint_text=_fingerprint(message),
        original_reply_required=original_reply_required,
        corrected_reply_required=False,
        note=note,
    )
    db.add(feedback)

    if analysis and analysis.classification_json:
        data = json.loads(analysis.classification_json)
        data["reply_required"] = False
        correction_note = "\n[ユーザー修正] 返信不要として学習されました。"
        data["rationale"] = (data.get("rationale") or "") + correction_note
        analysis.classification_json = json.dumps(data, ensure_ascii=False)

    db.commit()
    db.refresh(feedback)
    return feedback


async def get_similar_corrections(
    db: Session, message: Message, *, top_k: int = FEW_SHOT_TOP_K
) -> list[ClassificationFeedback]:
    all_feedback = db.query(ClassificationFeedback).all()
    if not all_feedback:
        return []  # skip the embedding call entirely when there's nothing to compare against

    embedder = get_embedding_provider()
    texts = [_fingerprint(message)] + [f.fingerprint_text for f in all_feedback]
    vectors = await embedder.embed(texts)
    target_vec, other_vecs = vectors[0], vectors[1:]

    scored = [(f, cosine_similarity(target_vec, vec)) for f, vec in zip(all_feedback, other_vecs)]
    scored = [pair for pair in scored if pair[1] >= FEW_SHOT_SIMILARITY_THRESHOLD]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [f for f, _ in scored[:top_k]]


def build_few_shot_suffix(corrections: list[ClassificationFeedback]) -> str:
    if not corrections:
        return ""
    lines = ["\n\n過去のユーザー修正例（参考にしてください。今回のメールにも同様の傾向があれば考慮してください）:"]
    for c in corrections:
        if c.corrected_mail_type is not None:
            original = c.original_mail_type or "未分類"
            lines.append(
                f'- 件名/本文の抜粋「{c.fingerprint_text[:80]}」は当初「{original}」と分類されましたが、'
                f"正しくは「{c.corrected_mail_type}」でした。"
            )
        if c.corrected_reply_required is not None:
            lines.append(
                f'- 件名/本文の抜粋「{c.fingerprint_text[:80]}」は返信要否が'
                f'「{"要返信" if c.corrected_reply_required else "返信不要"}」と修正されました。'
            )
    return "\n".join(lines)
