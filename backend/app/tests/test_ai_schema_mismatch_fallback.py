"""Regression coverage for a real user report: clicking "AI分類を実行"
against a real OpenAI-compatible provider raised an unhandled 500
("AI分類に失敗しました" with no further detail). Root cause: OpenAI's
response_format=json_object only guarantees syntactically valid JSON, not
that it matches ClassificationResult/ExtractionResult's shape — a response
missing the required `mail_type` field (or nesting the combined
classification/extraction call differently than asked) raised pydantic's
ValidationError, which wasn't caught anywhere alongside LLMProviderError
and so wasn't covered by the existing offline-fallback behavior.

These tests fake a provider that returns valid-but-wrong-shaped JSON (the
network call succeeds, so LLMProviderError never fires) and verify each
service now falls back to LocalMockProvider instead of raising.
"""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.services import analysis_service, classification_service, extraction_service


class _WrongShapeProvider:
    """Simulates a real LLM that returned syntactically valid JSON not
    matching the schema we asked for — no missing-key/network exception,
    just a shape complete_json's caller can't validate (missing the
    required ClassificationResult.mail_type)."""

    name = "wrong_shape_provider"

    async def complete_json(self, *, system_prompt: str, user_prompt: str):
        return {"totally_unexpected_key": "not what we asked for"}, LLMResponse(text="{}")

    async def complete_text(self, *, system_prompt: str, user_prompt: str):
        raise NotImplementedError


class _WrongFieldTypeProvider:
    """ExtractionResult is fully optional/extra="allow", so an unknown key
    alone doesn't fail validation like ClassificationResult's missing
    mail_type does — this instead sends a field with the wrong type
    (headcount expects int | None) to trigger the same ValidationError
    path for extraction_service."""

    name = "wrong_field_type_provider"

    async def complete_json(self, *, system_prompt: str, user_prompt: str):
        return {"headcount": "many people"}, LLMResponse(text="{}")

    async def complete_text(self, *, system_prompt: str, user_prompt: str):
        raise NotImplementedError


def _make_message(db_session) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_classify_message_falls_back_when_provider_json_does_not_match_schema(db_session, monkeypatch):
    monkeypatch.setattr(classification_service, "get_llm_provider", lambda: _WrongShapeProvider())
    message = _make_message(db_session)

    outcome = await classification_service.classify_message(db_session, message)

    assert outcome.analysis.is_fallback is True
    assert outcome.result.mail_type  # LocalMockProvider always fills this in


@pytest.mark.asyncio
async def test_extract_message_falls_back_when_provider_json_does_not_match_schema(db_session, monkeypatch):
    monkeypatch.setattr(extraction_service, "get_llm_provider", lambda: _WrongFieldTypeProvider())
    message = _make_message(db_session)

    outcome = await extraction_service.extract_message(db_session, message)

    assert outcome.is_fallback is True
    assert outcome.result is not None


@pytest.mark.asyncio
async def test_analyze_message_falls_back_when_provider_json_does_not_match_schema(db_session, monkeypatch):
    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _WrongShapeProvider())
    message = _make_message(db_session)

    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.is_fallback is True
    assert outcome.classification.mail_type
