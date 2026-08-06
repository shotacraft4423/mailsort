"""Regression coverage: "メールフォルダそれぞれで検索とかフィルターを
使った絞り込みできるようにして" — /search and /search/natural used to
search every folder in every account unconditionally, with no way to
narrow a search to just the folder currently open. Also covers
/search/natural actually asking the LLM to translate a free-text query
into a structured filter ("そこでもプロンプト使えるように"), falling back
to the existing regex heuristic when AI is off/unavailable/fails."""
from __future__ import annotations

import json

import pytest

from app.db.models.ai import AIAnalysis
from app.db.models.email import EmailAccount, Message
from app.providers.llm.base import LLMResponse
from app.services import search_service


def _make_account(db_session, email="a@example.com") -> EmailAccount:
    account = EmailAccount(display_name="a", email_address=email, protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    return account


def test_plain_search_is_scoped_to_folder(db_session):
    account = _make_account(db_session)
    db_session.add(
        Message(account_id=account.id, message_uid="1", subject="Java案件のご紹介", sender_address="a@b.com", folder="案件")
    )
    db_session.add(
        Message(account_id=account.id, message_uid="2", subject="Java案件のご紹介", sender_address="a@b.com", folder="INBOX")
    )
    db_session.commit()

    backend = search_service.SqliteLikeBackend()
    scoped = backend.search(db_session, "Java", folder="案件")
    unscoped = backend.search(db_session, "Java")

    assert len(scoped) == 1
    assert scoped[0].folder == "案件"
    assert len(unscoped) == 2


def test_plain_search_is_scoped_to_account(db_session):
    account_a = _make_account(db_session, "a@example.com")
    account_b = _make_account(db_session, "b@example.com")
    db_session.add(Message(account_id=account_a.id, message_uid="1", subject="案件のご紹介", sender_address="x@y.com"))
    db_session.add(Message(account_id=account_b.id, message_uid="1", subject="案件のご紹介", sender_address="x@y.com"))
    db_session.commit()

    backend = search_service.SqliteLikeBackend()
    scoped = backend.search(db_session, "案件", account_id=account_a.id)

    assert len(scoped) == 1
    assert scoped[0].account_id == account_a.id


@pytest.mark.asyncio
async def test_ai_search_falls_back_to_heuristic_when_provider_is_local_mock(db_session):
    account = _make_account(db_session)
    db_session.add(
        Message(account_id=account.id, message_uid="1", subject="React案件のご紹介", sender_address="a@b.com", folder="案件")
    )
    db_session.add(
        Message(account_id=account.id, message_uid="2", subject="React案件のご紹介", sender_address="a@b.com", folder="INBOX")
    )
    db_session.commit()

    # conftest's default test settings point llm_provider at local_mock, so
    # ai_search must behave exactly like the always-available heuristic —
    # not silently return nothing just because there's no real provider.
    results = await search_service.ai_search(db_session, "React", folder="案件")

    assert len(results) == 1
    assert results[0].folder == "案件"


@pytest.mark.asyncio
async def test_ai_search_applies_a_real_providers_structured_filter(db_session, monkeypatch):
    account = _make_account(db_session)
    deal_message = Message(
        account_id=account.id, message_uid="1", subject="件名A", sender_address="a@b.com", folder="INBOX"
    )
    candidate_message = Message(
        account_id=account.id, message_uid="2", subject="件名B", sender_address="a@b.com", folder="INBOX"
    )
    db_session.add_all([deal_message, candidate_message])
    db_session.flush()
    db_session.add(
        AIAnalysis(
            message_id=deal_message.id,
            content_hash="h1",
            provider_used="fake",
            classification_json=json.dumps({"mail_type": "案件紹介"}),
            extraction_json="{}",
        )
    )
    db_session.add(
        AIAnalysis(
            message_id=candidate_message.id,
            content_hash="h2",
            provider_used="fake",
            classification_json=json.dumps({"mail_type": "人材紹介"}),
            extraction_json="{}",
        )
    )
    db_session.commit()

    class _FakeProvider:
        name = "fake_llm"

        async def complete_json(self, *, system_prompt: str, user_prompt: str):
            return {"mail_type": "案件紹介"}, LLMResponse(text="{}")

    monkeypatch.setattr(search_service, "get_llm_provider", lambda: _FakeProvider())

    results = await search_service.ai_search(db_session, "案件だけ見せて")

    assert [m.id for m in results] == [deal_message.id]
