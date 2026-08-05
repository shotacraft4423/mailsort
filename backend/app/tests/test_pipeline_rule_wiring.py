"""Regression coverage: rule_engine.evaluate_rules/apply_actions and
plugin_manager.dispatch_message_classified were configurable via the GUI
(/rules, /plugins) but the automatic analysis pipeline never called them —
a rule saved through the admin UI silently never fired. This verifies
analysis_service.analyze_message() now actually applies matching rules.
"""
from __future__ import annotations

import json

import pytest

from app.db.models.email import EmailAccount, Message
from app.db.models.rule import Rule
from app.db.models.tag import MessageTag, Tag
from app.services import analysis_service


@pytest.mark.asyncio
async def test_analyze_message_applies_matching_rule_tag(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="Java案件のご紹介",
        sender_address="sales@important-client.co.jp",
        body_text="Java案件のご紹介です。",
    )
    db_session.add(message)

    rule = Rule(
        name="重要顧客は常に重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "important-client"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "重要"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    await analysis_service.analyze_message(db_session, message)

    tag = db_session.query(Tag).filter(Tag.name == "重要").one_or_none()
    assert tag is not None
    message_tag = db_session.query(MessageTag).filter(MessageTag.message_id == message.id).one_or_none()
    assert message_tag is not None
    assert message_tag.source == "rule"


@pytest.mark.asyncio
async def test_analyze_message_applies_rule_on_cached_path_too(db_session):
    """A rule created *after* the first analysis must still apply the next
    time the (now-cached) message is analyzed — rules re-evaluate on every
    call, cache hit or not."""
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="件名",
        sender_address="sales@important-client.co.jp",
        body_text="本文",
    )
    db_session.add(message)
    db_session.commit()

    await analysis_service.analyze_message(db_session, message)
    assert db_session.query(MessageTag).filter(MessageTag.message_id == message.id).count() == 0

    rule = Rule(
        name="重要顧客は常に重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "important-client"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "重要"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    outcome = await analysis_service.analyze_message(db_session, message)
    assert outcome.from_cache is True
    assert db_session.query(MessageTag).filter(MessageTag.message_id == message.id).count() == 1


@pytest.mark.asyncio
async def test_analyze_message_does_not_crash_when_no_plugins_enabled(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", body_text="本文")
    db_session.add(message)
    db_session.commit()

    outcome = await analysis_service.analyze_message(db_session, message)
    assert outcome.classification is not None
