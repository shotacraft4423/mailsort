"""Round 4 of the same real-world AI-JSON-shape-drift bug class (see
classification_service.normalize_classification_payload's docstring for
rounds 1-3): tool_links is a single nested ToolLinks object, but the model
sometimes flattens it into a bare list of URL strings —
['https://gy53.asp.cuenote.jp/...'] or [] — instead of
{"other_urls": [...]}. normalize_extraction_payload buckets each URL by
domain (rather than dumping everything into other_urls) so
meeting_extraction_service's extraction.tool_links.teams/meet/zoom lookups
keep working even when the model gets the shape wrong."""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.schemas.extraction import ExtractionResult
from app.services import analysis_service, extraction_service
from app.services.extraction_service import normalize_extraction_payload


def test_empty_list_becomes_an_empty_tool_links_object():
    raw = {"tool_links": []}

    normalized = normalize_extraction_payload(raw)

    assert normalized["tool_links"] == {}
    ExtractionResult.model_validate(normalized)


def test_unrecognized_url_is_bucketed_into_other_urls():
    raw = {"tool_links": ["https://gy53.asp.cuenote.jp/h/X8UkSzbL8yW91H5GTK"]}

    normalized = normalize_extraction_payload(raw)

    assert normalized["tool_links"] == {"other_urls": ["https://gy53.asp.cuenote.jp/h/X8UkSzbL8yW91H5GTK"]}
    result = ExtractionResult.model_validate(normalized)
    assert result.tool_links.other_urls == ["https://gy53.asp.cuenote.jp/h/X8UkSzbL8yW91H5GTK"]


def test_known_tool_urls_are_bucketed_by_domain_not_dumped_into_other_urls():
    raw = {
        "tool_links": [
            "https://teams.microsoft.com/l/meetup-join/abc",
            "https://us02web.zoom.us/j/123",
            "https://meet.google.com/xyz-abcd-efg",
        ]
    }

    normalized = normalize_extraction_payload(raw)

    result = ExtractionResult.model_validate(normalized)
    assert result.tool_links.teams == ["https://teams.microsoft.com/l/meetup-join/abc"]
    assert result.tool_links.zoom == ["https://us02web.zoom.us/j/123"]
    assert result.tool_links.meet == ["https://meet.google.com/xyz-abcd-efg"]
    assert result.tool_links.other_urls == []


def test_lone_string_instead_of_a_list_is_wrapped_and_bucketed():
    raw = {"tool_links": "https://teams.microsoft.com/l/meetup-join/abc"}

    normalized = normalize_extraction_payload(raw)

    assert normalized["tool_links"] == {"teams": ["https://teams.microsoft.com/l/meetup-join/abc"]}


def test_well_formed_tool_links_pass_through_unchanged():
    raw = {"tool_links": {"teams": ["https://teams.microsoft.com/l/meetup-join/abc"]}}

    normalized = normalize_extraction_payload(raw)

    assert normalized["tool_links"] == {"teams": ["https://teams.microsoft.com/l/meetup-join/abc"]}


def _make_message(db_session) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_extract_message_no_longer_falls_back_on_the_exact_logged_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return ({"tool_links": ["https://gy53.asp.cuenote.jp/h/X8UkSzbL8yW91H5GTK"]}, LLMResponse(text="{}"))

    monkeypatch.setattr(extraction_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await extraction_service.extract_message(db_session, message)

    assert outcome.is_fallback is False
    assert outcome.result.tool_links.other_urls == ["https://gy53.asp.cuenote.jp/h/X8UkSzbL8yW91H5GTK"]


@pytest.mark.asyncio
async def test_analyze_message_no_longer_falls_back_on_the_exact_logged_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {
                    "classification": {"mail_type": "案件紹介"},
                    "extraction": {"tool_links": []},
                },
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.is_fallback is False
