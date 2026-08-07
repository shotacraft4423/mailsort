"""Round 8 of the real-world AI-JSON-shape-drift bug class (see
ai_schema_normalization's module docstring for rounds 1-7): right key, right
outer list[str] shape, but a bulk "reclassify offline messages" run against
a multi-candidate email produced skills=[["Java","MySQL","Oracle",...],
["SQL","VBA","Office"]] instead of a flat list of strings — the model
grouped each candidate's skills into its own sub-list instead of flattening
them into ExtractionResult.skills: list[str]. normalize_for_schema's list[T]
branch now flattens any non-string item in a list[str] field rather than
letting pydantic reject the whole payload."""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.schemas.extraction import ExtractionResult
from app.services import analysis_service, extraction_service
from app.services.extraction_service import normalize_extraction_payload


def test_list_of_lists_is_flattened_into_one_string_per_item():
    raw = {"skills": [["Java", "MySQL", "Oracle"], ["SQL", "VBA", "Office"]]}

    normalized = normalize_extraction_payload(raw)

    assert normalized["skills"] == ["Java、MySQL、Oracle", "SQL、VBA、Office"]
    ExtractionResult.model_validate(normalized)


def test_the_exact_logged_multi_candidate_payload():
    raw = {
        "skills": [
            ["サーバ構築", "単体テスト", "基地局経験"],
            ["サーバ構築", "運用保守", "ドキュメント作成"],
            ["構築", "運用保守"],
            ["サーバ構築", "自動化ツール開発"],
        ]
    }

    normalized = normalize_extraction_payload(raw)

    assert len(normalized["skills"]) == 4
    assert all(isinstance(item, str) for item in normalized["skills"])
    ExtractionResult.model_validate(normalized)


def test_mixed_strings_and_sublists_only_flattens_the_sublists():
    raw = {"skills": ["Python", ["Java", "MySQL"]]}

    normalized = normalize_extraction_payload(raw)

    assert normalized["skills"] == ["Python", "Java、MySQL"]


def test_well_formed_skills_pass_through_unchanged():
    raw = {"skills": ["Java", "MySQL"]}

    normalized = normalize_extraction_payload(raw)

    assert normalized["skills"] == ["Java", "MySQL"]


def _make_message(db_session) -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_extract_message_no_longer_falls_back_on_the_exact_round8_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {"skills": [["Java", "MySQL", "Oracle"], ["SQL", "VBA", "Office"]]},
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(extraction_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await extraction_service.extract_message(db_session, message)

    assert outcome.is_fallback is False
    assert outcome.result.skills == ["Java、MySQL、Oracle", "SQL、VBA、Office"]


@pytest.mark.asyncio
async def test_analyze_message_no_longer_falls_back_on_the_exact_round8_payload(db_session, monkeypatch):
    class _RealisticButNonConformingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return (
                {
                    "classification": {"mail_type": "人材紹介"},
                    "extraction": {"skills": [["サーバ構築", "単体テスト"], ["構築", "運用保守"]]},
                },
                LLMResponse(text="{}"),
            )

    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _RealisticButNonConformingProvider())
    message = _make_message(db_session)

    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.is_fallback is False
    assert outcome.extraction.skills == ["サーバ構築、単体テスト", "構築、運用保守"]
