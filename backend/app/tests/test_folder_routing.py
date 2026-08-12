"""Regression coverage: classification produced tags/badges the user had
to go looking for, but nothing ever moved a message anywhere based on the
result — every classified message just sat in INBOX regardless of
category. analyze_message now routes INBOX messages into a matching local
folder (案件/人材/重要/要返信/Junk) once classified.
"""
from __future__ import annotations

import json

import pytest

from app.db.models.ai import AIAnalysis
from app.db.models.email import Attachment, EmailAccount, Message
from app.services import analysis_service


def _make_message(db_session, *, subject: str, body_text: str, folder: str = "INBOX") -> Message:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject=subject, sender_address="a@b.com", body_text=body_text, folder=folder)
    db_session.add(message)
    db_session.commit()
    return message


@pytest.mark.asyncio
async def test_deal_introduction_email_is_routed_to_deal_folder(db_session):
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。")

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "案件"


@pytest.mark.asyncio
async def test_candidate_introduction_email_is_routed_to_candidate_folder(db_session):
    message = _make_message(db_session, subject="人材のご紹介", body_text="人材のご紹介です。")

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "人材"


@pytest.mark.asyncio
async def test_message_not_in_inbox_is_never_moved(db_session):
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。", folder="Archive")

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "Archive"


@pytest.mark.asyncio
async def test_message_misrouted_to_the_wrong_auto_folder_gets_corrected(db_session):
    """A real user report: a 人材紹介 message ended up filed under 案件 (and
    人材 stayed empty) and running "AI分類を実行"/bulk-classify again did
    not fix it — because the message was no longer in INBOX, the old guard
    treated it as "already filed on purpose" and left it exactly where it
    (wrongly) already was. Re-routing must be able to correct its own past
    decisions, not just file brand-new INBOX mail."""
    message = _make_message(db_session, subject="人材のご紹介", body_text="人材のご紹介です。", folder="案件")

    await analysis_service.analyze_message(db_session, message, force=True)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "人材"


@pytest.mark.asyncio
async def test_message_manually_filed_by_a_rule_into_a_custom_folder_is_left_alone(db_session):
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。", folder="最重要顧客")

    await analysis_service.analyze_message(db_session, message, force=True)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "最重要顧客"


@pytest.mark.asyncio
async def test_routing_disabled_via_settings_leaves_message_in_inbox(db_session, monkeypatch):
    monkeypatch.setenv("MAILSORT_AUTO_ROUTE_BY_CLASSIFICATION", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。")

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "INBOX"


@pytest.mark.asyncio
async def test_a_cached_reclassify_still_routes_a_message_that_was_never_routed(db_session, monkeypatch):
    """Reproduces "全部分類したのにフォルダ分けされない": a message analyzed
    while routing was off (or before routing existed at all) has a cached
    AIAnalysis row. Re-running "AI分類を実行"/bulk-classify without
    force=True hits that cache — routing must still apply there, not only
    on a fresh (uncached) analysis."""
    from app.core.config import get_settings

    monkeypatch.setenv("MAILSORT_AUTO_ROUTE_BY_CLASSIFICATION", "false")
    get_settings.cache_clear()
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。")
    await analysis_service.analyze_message(db_session, message)
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "INBOX"

    monkeypatch.setenv("MAILSORT_AUTO_ROUTE_BY_CLASSIFICATION", "true")
    get_settings.cache_clear()
    outcome = await analysis_service.analyze_message(db_session, message)

    assert outcome.from_cache is True
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "案件"


def test_reroute_classified_messages_fixes_mail_stuck_in_the_wrong_folder_without_calling_the_llm(db_session):
    """"すでに割り振られてしまったメールの再振り分けを行えるようにして" —
    a message already misfiled under 案件 by an earlier, buggier pass has
    no reason to ever get re-analyzed: it's not in INBOX, and bulk-classify
    only ever reads whichever folder is currently open. This must be able
    to fix it straight from the cached classification already sitting in
    AIAnalysis, without invoking the LLM provider at all."""
    message = _make_message(db_session, subject="人材のご紹介", body_text="人材のご紹介です。", folder="案件")
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="irrelevant",
            provider_used="local_mock",
            classification_json=json.dumps(
                {"mail_type": "人材紹介", "categories": [{"label": "人材紹介", "confidence": 1.0}], "reply_required": False}
            ),
            extraction_json="{}",
        )
    )
    db_session.commit()

    moved = analysis_service.reroute_classified_messages(db_session)

    assert moved == 1
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "人材"


def test_urgent_priority_mail_with_no_more_specific_category_routes_to_important_folder(db_session):
    """"重要の分類もできていない" — top_category() is a single argmax over
    categories, so a message tagged both 案件紹介 (0.9) and 重要 (0.6) always
    routes to 案件, never 重要, no matter how important it also is. priority
    is a separate, deterministic signal the model produces regardless of
    which category won — this is the fallback for a message whose category
    didn't map anywhere more specific but whose priority says it matters."""
    message = _make_message(db_session, subject="至急ご確認ください", body_text="クレームのご連絡です。")
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="irrelevant",
            provider_used="local_mock",
            classification_json=json.dumps(
                {
                    "mail_type": "営業メール",
                    "categories": [{"label": "営業メール", "confidence": 0.8}],
                    "priority": "urgent",
                    "reply_required": False,
                }
            ),
            extraction_json="{}",
        )
    )
    db_session.commit()

    moved = analysis_service.reroute_classified_messages(db_session)

    assert moved == 1
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "重要"


def test_reply_required_still_wins_over_urgent_priority_when_both_are_true(db_session):
    """reply_required routing is more specific/actionable than the generic
    重要 catch-all, so it keeps priority when both signals fire on the same
    message (existing behavior — this locks in that the new priority-based
    fallback doesn't change it)."""
    message = _make_message(db_session, subject="至急ご確認ください", body_text="ご確認をお願いします。")
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="irrelevant",
            provider_used="local_mock",
            classification_json=json.dumps(
                {
                    "mail_type": "営業メール",
                    "categories": [{"label": "営業メール", "confidence": 0.8}],
                    "priority": "urgent",
                    "reply_required": True,
                }
            ),
            extraction_json="{}",
        )
    )
    db_session.commit()

    moved = analysis_service.reroute_classified_messages(db_session)

    assert moved == 1
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "要返信"


def test_normal_priority_mail_with_no_category_match_is_left_in_inbox(db_session):
    message = _make_message(db_session, subject="お知らせ", body_text="定期のお知らせです。")
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="irrelevant",
            provider_used="local_mock",
            classification_json=json.dumps(
                {
                    "mail_type": "営業メール",
                    "categories": [{"label": "営業メール", "confidence": 0.8}],
                    "priority": "normal",
                    "reply_required": False,
                }
            ),
            extraction_json="{}",
        )
    )
    db_session.commit()

    moved = analysis_service.reroute_classified_messages(db_session)

    assert moved == 0
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "INBOX"


def test_reroute_classified_messages_leaves_correctly_filed_mail_untouched(db_session):
    message = _make_message(db_session, subject="Java案件のご紹介", body_text="Java案件のご紹介です。", folder="案件")
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="irrelevant",
            provider_used="local_mock",
            classification_json=json.dumps(
                {"mail_type": "案件紹介", "categories": [{"label": "案件紹介", "confidence": 1.0}], "reply_required": False}
            ),
            extraction_json="{}",
        )
    )
    db_session.commit()

    moved = analysis_service.reroute_classified_messages(db_session)

    assert moved == 0
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "案件"


@pytest.mark.asyncio
async def test_message_with_skill_sheet_attachment_is_routed_to_candidate_folder_even_when_the_llm_says_deal(db_session):
    """A real user report: a mail with a skill-sheet spreadsheet attached
    landed in 案件 because the model's category scores came back tied
    (案件紹介/人材紹介/日程調整/請求/広告 all at 55%). "基本的にスキルシート
    が添付...されているものは案件ではなく人材です" — whether an attachment
    is a skill sheet is already determined deterministically by
    attachment_analysis_service, so routing must trust that signal over a
    close/ambiguous category call."""
    message = _make_message(db_session, subject="【直個人】PMO案件のご紹介", body_text="案件のご紹介です。")
    db_session.add(Attachment(message_id=message.id, file_name="スキルシート.xlsx", classified_kind="skill_sheet"))
    db_session.commit()

    await analysis_service.analyze_message(db_session, message, force=True)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "人材"


def test_reroute_classified_messages_fixes_skill_sheet_mail_already_stuck_in_deal_folder(db_session):
    message = _make_message(db_session, subject="【直個人】PMO案件のご紹介", body_text="案件のご紹介です。", folder="案件")
    db_session.add(Attachment(message_id=message.id, file_name="スキルシート.xlsx", classified_kind="skill_sheet"))
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="irrelevant",
            provider_used="local_mock",
            classification_json=json.dumps(
                {
                    "mail_type": "案件紹介",
                    "categories": [
                        {"label": "案件紹介", "confidence": 0.55},
                        {"label": "人材紹介", "confidence": 0.55},
                    ],
                    "reply_required": False,
                }
            ),
            extraction_json="{}",
        )
    )
    db_session.commit()

    moved = analysis_service.reroute_classified_messages(db_session)

    assert moved == 1
    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "人材"
