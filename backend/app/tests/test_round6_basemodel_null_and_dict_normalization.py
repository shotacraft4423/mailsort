"""Round 6 of the real-world AI-JSON-shape-drift bug class, found immediately
after round 5's generic normalize_for_schema landed — and this one was a
genuine bug in that generic function, not just a new drift pattern:

1. tool_links (a *required* nested ToolLinks field, not Optional) coming
   back as bare `null`. normalize_for_schema's single-nested-BaseModel
   branch used to `continue` unconditionally for any BaseModel-typed field,
   so the "required field got null -> default" rule further down was never
   reached for tool_links specifically — it fell back to local_mock on
   every response missing tool_links, which defeats the entire point of
   the round-4 fix. Fixed by handling the required+null case inside the
   BaseModel branch itself.
2. meeting (MeetingInfo | None) coming back as a bare date/time string
   ("8/4(火) 17:00～18:00＠web") instead of {"datetime_text": "..."}.
   No generic rule can know how to re-nest arbitrary free text into an
   arbitrary model's fields, so this needed its own bucketizer, same as
   tool_links' domain-based one.
3. candidate_summary (str | None on ClassificationResult) coming back as a
   structured dict ({"name": "F.T", "age": 26, ...}) instead of prose.
   normalize_for_schema's scalar-collapse rule only handled list-shaped
   drift (round 5); this generalizes it to also flatten a dict into
   "key: value" text for any str field.
"""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.schemas.classification import ClassificationResult
from app.schemas.extraction import ExtractionResult
from app.services import analysis_service, classification_service, extraction_service
from app.services.classification_service import normalize_classification_payload
from app.services.extraction_service import normalize_extraction_payload


def test_required_tool_links_getting_null_becomes_an_empty_object():
    raw = {"tool_links": None}

    normalized = normalize_extraction_payload(raw)

    assert normalized["tool_links"] == {}
    result = ExtractionResult.model_validate(normalized)
    assert result.tool_links.other_urls == []


def test_bare_meeting_string_becomes_datetime_text():
    raw = {"meeting": "8/4(火) 17:00～18:00＠web"}

    normalized = normalize_extraction_payload(raw)

    assert normalized["meeting"] == {"datetime_text": "8/4(火) 17:00～18:00＠web"}
    result = ExtractionResult.model_validate(normalized)
    assert result.meeting.datetime_text == "8/4(火) 17:00～18:00＠web"


def test_candidate_summary_dict_is_flattened_to_text():
    raw = {
        "mail_type": "人材紹介",
        "candidate_summary": {"name": "F.T", "age": 26, "skill": "Java", "note": "特定技術の環境を運用"},
    }

    normalized = normalize_classification_payload(raw)

    assert normalized["candidate_summary"] == "name: F.T、age: 26、skill: Java、note: 特定技術の環境を運用"
    ClassificationResult.model_validate(normalized)


def _make_message(db_session) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_extract_message_no_longer_falls_back_on_null_tool_links(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return ({"tool_links": None}, LLMResponse(text="{}"))

    monkeypatch.setattr(extraction_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await extraction_service.extract_message(db_session, message)

    assert outcome.is_fallback is False


@pytest.mark.asyncio
async def test_analyze_message_no_longer_falls_back_on_the_exact_round6_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {
                    "classification": {
                        "mail_type": "人材紹介",
                        "candidate_summary": {"name": "F.T", "age": 26, "note": "特定技術の環境を運用"},
                    },
                    "extraction": {
                        "tool_links": None,
                        "meeting": "8/4(火) 17:00～18:00＠web",
                    },
                },
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.is_fallback is False
    assert outcome.extraction.meeting.datetime_text == "8/4(火) 17:00～18:00＠web"
    assert "F.T" in outcome.classification.candidate_summary
