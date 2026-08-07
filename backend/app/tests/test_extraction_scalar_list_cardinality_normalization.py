"""Round 5 of the real-world AI-JSON-shape-drift bug class (see
ai_schema_normalization.normalize_for_schema's docstring for rounds 1-4):
right keys, right nesting, but wrong *cardinality* — a str | None field like
candidate_name/unit_price/location/period came back as a list because the
real email genuinely mentioned multiple candidates/prices/locations/dates,
and list[str] fields (attachments_mentioned/todo/questions/unanswered_items)
came back as null instead of []. "根本的な仕組みごとの改革が必要ではない
でしょうか" — rather than add a 5th special case, normalize_extraction_payload
now runs through the generic, schema-introspecting normalize_for_schema,
which repairs both patterns (and any future field with the same annotation
shape) without a per-field patch."""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.schemas.extraction import ExtractionResult
from app.services import analysis_service, extraction_service
from app.services.extraction_service import normalize_extraction_payload


def test_str_field_receiving_a_list_is_joined_into_one_string():
    raw = {"candidate_name": ["F.D", "T.K", "T.M", "Y.R", "S.N", "I.R", "I.M"]}

    normalized = normalize_extraction_payload(raw)

    assert normalized["candidate_name"] == "F.D、T.K、T.M、Y.R、S.N、I.R、I.M"
    ExtractionResult.model_validate(normalized)


def test_unit_price_location_period_lists_are_joined_from_the_exact_logged_payload():
    raw = {
        "unit_price": ["55万", "75万", "85万", "65万", "88万"],
        "location": ["北越谷", "二子新地", "武蔵小杉駅"],
        "period": ["8月開始", "9月開始"],
    }

    normalized = normalize_extraction_payload(raw)

    assert normalized["unit_price"] == "55万、75万、85万、65万、88万"
    assert normalized["location"] == "北越谷、二子新地、武蔵小杉駅"
    assert normalized["period"] == "8月開始、9月開始"
    ExtractionResult.model_validate(normalized)


def test_empty_list_for_a_scalar_field_becomes_none():
    raw = {"candidate_name": []}

    normalized = normalize_extraction_payload(raw)

    assert normalized["candidate_name"] is None


def test_list_fields_receiving_null_become_empty_lists():
    raw = {
        "attachments_mentioned": None,
        "todo": None,
        "questions": None,
        "unanswered_items": None,
    }

    normalized = normalize_extraction_payload(raw)

    assert normalized["attachments_mentioned"] == []
    assert normalized["todo"] == []
    assert normalized["questions"] == []
    assert normalized["unanswered_items"] == []
    ExtractionResult.model_validate(normalized)


def test_well_formed_scalar_and_list_fields_pass_through_unchanged():
    raw = {"candidate_name": "Aさん", "todo": ["見積提出"]}

    normalized = normalize_extraction_payload(raw)

    assert normalized["candidate_name"] == "Aさん"
    assert normalized["todo"] == ["見積提出"]


def _make_message(db_session) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_extract_message_no_longer_falls_back_on_the_exact_round5_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {
                    "candidate_name": ["F.D", "T.K", "T.M", "Y.R", "S.N", "I.R", "I.M"],
                    "unit_price": ["55万", "75万", "85万", "65万", "88万"],
                    "location": ["北越谷", "二子新地", "武蔵小杉駅"],
                    "period": ["8月開始", "9月開始"],
                    "attachments_mentioned": None,
                    "todo": None,
                    "questions": None,
                    "unanswered_items": None,
                },
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(extraction_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await extraction_service.extract_message(db_session, message)

    assert outcome.is_fallback is False
    assert outcome.result.candidate_name == "F.D、T.K、T.M、Y.R、S.N、I.R、I.M"
    assert outcome.result.todo == []


@pytest.mark.asyncio
async def test_analyze_message_no_longer_falls_back_on_the_exact_round5_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {
                    "classification": {"mail_type": "人材紹介"},
                    "extraction": {
                        "candidate_name": ["F.D", "T.K"],
                        "unit_price": ["55万", "75万"],
                        "attachments_mentioned": None,
                        "todo": None,
                    },
                },
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.is_fallback is False
    assert outcome.extraction.candidate_name == "F.D、T.K"
    assert outcome.extraction.todo == []
