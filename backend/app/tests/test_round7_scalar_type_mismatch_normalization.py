"""Round 7 of the real-world AI-JSON-shape-drift bug class (see
ai_schema_normalization's module docstring for rounds 1-6): right keys,
right nesting, but the scalar's own type was swapped with a neighboring
one - a str field given a bare number (age: str | None getting 26,
unit_price: str | None getting a raw int like 650000), or an int field
given a string with the number still embedded in units/counters the model
left in (headcount: int | None getting "2名", interview_count: int | None
getting "1回"). All three came from the same production log batch, right
after round 6's fix landed - confirming the generic, type-driven approach
keeps paying off without a bespoke patch per field."""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.schemas.extraction import ExtractionResult
from app.services import analysis_service, extraction_service
from app.services.extraction_service import normalize_extraction_payload


def test_str_field_receiving_a_bare_int_is_stringified():
    raw = {"age": 26}

    normalized = normalize_extraction_payload(raw)

    assert normalized["age"] == "26"
    ExtractionResult.model_validate(normalized)


def test_str_field_receiving_a_bare_int_price_is_stringified():
    raw = {"unit_price": 650000}

    normalized = normalize_extraction_payload(raw)

    assert normalized["unit_price"] == "650000"


def test_int_field_receiving_a_string_with_a_counter_suffix_is_parsed():
    raw = {"headcount": "2名", "interview_count": "1回"}

    normalized = normalize_extraction_payload(raw)

    assert normalized["headcount"] == 2
    assert normalized["interview_count"] == 1
    ExtractionResult.model_validate(normalized)


def test_int_field_receiving_a_non_numeric_string_is_left_alone():
    raw = {"headcount": "複数名"}

    normalized = normalize_extraction_payload(raw)

    assert normalized["headcount"] == "複数名"


def test_well_formed_scalar_fields_pass_through_unchanged():
    raw = {"age": "20代", "headcount": 3}

    normalized = normalize_extraction_payload(raw)

    assert normalized["age"] == "20代"
    assert normalized["headcount"] == 3


def _make_message(db_session) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_extract_message_no_longer_falls_back_on_the_exact_round7_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {"age": 26, "headcount": "2名", "interview_count": "1回", "unit_price": 650000},
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(extraction_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await extraction_service.extract_message(db_session, message)

    assert outcome.is_fallback is False
    assert outcome.result.age == "26"
    assert outcome.result.headcount == 2
    assert outcome.result.interview_count == 1
    assert outcome.result.unit_price == "650000"


@pytest.mark.asyncio
async def test_analyze_message_no_longer_falls_back_on_the_exact_round7_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {
                    "classification": {"mail_type": "人材紹介"},
                    "extraction": {"age": 26, "headcount": "2名", "interview_count": "1回"},
                },
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.is_fallback is False
    assert outcome.extraction.age == "26"
    assert outcome.extraction.headcount == 2
