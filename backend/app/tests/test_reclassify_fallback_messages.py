"""Coverage for the "オフライン分類のメールだけ再分類" bulk action —
analysis_service.reclassify_fallback_messages / POST /ai/reclassify-fallback.
Root cause this addresses: bulk-classify and 再分類 both call
analyze_message without force for content that hasn't changed, which is a
cache hit that never touches the provider again — so a message that fell
back once stays on the offline result forever with no error to look at.
This targets exactly (and only) the messages flagged is_fallback."""
from __future__ import annotations

import pytest

from app.db.models.ai import AIAnalysis
from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.services import analysis_service


def _make_message(db_session, *, is_fallback: bool, folder: str = "INBOX") -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(
        account_id=account.id, message_uid="1", subject="案件のご紹介", sender_address="a@b.com", body_text="案件のご紹介です。", folder=folder
    )
    db_session.add(message)
    db_session.flush()
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="stale-hash-does-not-matter-because-we-force",
            provider_used="local_mock" if is_fallback else "openai_compatible",
            is_fallback=is_fallback,
            classification_json='{"mail_type": "案件紹介", "categories": []}',
            extraction_json="{}",
        )
    )
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_only_fallback_messages_are_reclassified(db_session, monkeypatch):
    fallback_message = _make_message(db_session, is_fallback=True)
    already_good_message = _make_message(db_session, is_fallback=False)

    class _WorkingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            if "統合解析タスク" in system_prompt:
                return {"classification": {"mail_type": "案件紹介", "categories": []}, "extraction": {}}, LLMResponse(text="{}")
            return {"mail_type": "案件紹介", "categories": []}, LLMResponse(text="{}")

    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _WorkingProvider())

    result = await analysis_service.reclassify_fallback_messages(db_session)

    assert result == {"attempted": 1, "recovered": 1, "still_fallback": 0}
    assert (
        db_session.query(AIAnalysis).filter(AIAnalysis.message_id == fallback_message.id).one().is_fallback is False
    )
    # untouched — was never fallback, so reclassify_fallback_messages must
    # not have even looked at it (no wasted LLM call)
    assert (
        db_session.query(AIAnalysis).filter(AIAnalysis.message_id == already_good_message.id).one().provider_used
        == "openai_compatible"
    )


@pytest.mark.asyncio
async def test_reports_still_fallback_when_the_provider_is_still_broken(db_session, monkeypatch):
    _make_message(db_session, is_fallback=True)

    from app.providers.llm.base import LLMProviderError

    class _StillBrokenProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            raise LLMProviderError("still failing")

    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _StillBrokenProvider())

    result = await analysis_service.reclassify_fallback_messages(db_session)

    assert result == {"attempted": 1, "recovered": 0, "still_fallback": 1}


@pytest.mark.asyncio
async def test_scoped_to_folder(db_session, monkeypatch):
    _make_message(db_session, is_fallback=True, folder="案件")
    _make_message(db_session, is_fallback=True, folder="人材")

    class _WorkingProvider:
        name = "openai_compatible"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return {"classification": {"mail_type": "案件紹介", "categories": []}, "extraction": {}}, LLMResponse(text="{}")

    monkeypatch.setattr(analysis_service, "get_llm_provider", lambda: _WorkingProvider())

    result = await analysis_service.reclassify_fallback_messages(db_session, folder="案件")

    assert result["attempted"] == 1
