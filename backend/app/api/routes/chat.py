"""AIチャット: minimal retrieval-augmented answer over the mailbox.

Retrieval today is the same LIKE-based search used by /search (see
search_service.py's docstring on why) — good enough to demo "先月案件紹介が
多かった会社" style questions on a small mailbox. Phase 2 swaps this for a
vector-search retriever (Chroma/pgvector/Qdrant per DESIGN.md) plus
LangGraph for multi-step questions.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.security import mask_text
from app.db.models.email import Message
from app.providers.llm.base import LLMProviderError
from app.providers.llm.registry import get_llm_provider

router = APIRouter(prefix="/chat", tags=["chat"])

SYSTEM_PROMPT = (
    "あなたはSES営業担当者のメールボックスに関する質問に答えるアシスタントです。"
    "与えられたメール抜粋のみを根拠に、日本語で簡潔に回答してください。"
    "根拠が無い場合は「わかりません」と答えてください。"
)


class ChatRequest(BaseModel):
    question: str
    context_limit: int = 20


class ChatResponse(BaseModel):
    answer: str
    source_message_ids: list[str]


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    messages = (
        db.query(Message)
        .order_by(Message.received_at.desc())
        .limit(payload.context_limit)
        .all()
    )

    context_lines = []
    for m in messages:
        snippet = mask_text((m.body_text or "")[:300])
        context_lines.append(f"[{m.id}] 件名: {m.subject} / 送信元: {m.sender_address}\n{snippet}")
    context = "\n\n".join(context_lines) or "(メールがありません)"

    user_prompt = f"質問: {payload.question}\n\nメール抜粋:\n{context}"

    provider = get_llm_provider()
    try:
        response = await provider.complete_text(system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt)
        answer = response.text
    except LLMProviderError:
        answer = "AIプロバイダーが利用できないため、チャット応答を生成できません。通常の検索機能をご利用ください。"

    return ChatResponse(answer=answer, source_message_ids=[m.id for m in messages])
