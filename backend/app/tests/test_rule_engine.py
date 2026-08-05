from __future__ import annotations

import json

from app.db.models.email import EmailAccount, Message
from app.db.models.rule import Rule
from app.db.models.tag import MessageTag, Tag
from app.services.rule_engine import apply_actions, evaluate_rules


def test_rule_fires_when_condition_matches(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="お見積りの件",
        sender_address="contact@important-client.co.jp",
        body_text="いつもお世話になっております。",
    )
    db_session.add(message)

    rule = Rule(
        name="重要顧客は常に重要",
        is_active=True,
        match_mode="all",
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "important-client"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "重要"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    fired = evaluate_rules(db_session, message, analysis=None)
    assert len(fired) == 1
    assert fired[0].rule.name == "重要顧客は常に重要"
    assert fired[0].actions == [{"type": "tag", "params": {"tag": "重要"}}]


def test_inactive_rule_does_not_fire(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(account_id=account.id, message_uid="1", subject="x", sender_address="a@b.com")
    db_session.add(message)

    rule = Rule(
        name="disabled rule",
        is_active=False,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "b.com"}]),
        actions_json=json.dumps([{"type": "tag", "params": {}}]),
    )
    db_session.add(rule)
    db_session.commit()

    assert evaluate_rules(db_session, message, analysis=None) == []


def test_apply_actions_creates_message_tag_from_tag_action(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="x", sender_address="a@important-client.co.jp")
    db_session.add(message)

    rule = Rule(
        name="重要顧客は常に重要",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "important-client"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "重要"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    fired = evaluate_rules(db_session, message, analysis=None)
    apply_actions(db_session, message, fired)

    tag = db_session.query(Tag).filter(Tag.name == "重要").one()
    message_tag = db_session.query(MessageTag).filter(MessageTag.message_id == message.id).one()
    assert message_tag.tag_id == tag.id
    assert message_tag.source == "rule"
    assert message_tag.confidence == 1.0


def test_apply_actions_does_not_duplicate_tag_on_repeated_fire(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="x", sender_address="a@b.com")
    db_session.add(message)
    rule = Rule(
        name="r",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "b.com"}]),
        actions_json=json.dumps([{"type": "tag", "params": {"tag": "重要"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    for _ in range(2):
        fired = evaluate_rules(db_session, message, analysis=None)
        apply_actions(db_session, message, fired)

    count = db_session.query(MessageTag).filter(MessageTag.message_id == message.id).count()
    assert count == 1


def test_apply_actions_ignores_unrecognized_action_types(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="x", sender_address="a@b.com")
    db_session.add(message)
    rule = Rule(
        name="notify only",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "b.com"}]),
        actions_json=json.dumps([{"type": "notify_slack", "params": {}}]),
    )
    db_session.add(rule)
    db_session.commit()

    fired = evaluate_rules(db_session, message, analysis=None)
    apply_actions(db_session, message, fired)  # must not raise

    assert db_session.query(MessageTag).count() == 0


def test_unmatched_condition_does_not_fire(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(account_id=account.id, message_uid="1", subject="x", sender_address="a@other.com")
    db_session.add(message)

    rule = Rule(
        name="only important-client",
        is_active=True,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "important-client"}]),
        actions_json=json.dumps([{"type": "tag", "params": {}}]),
    )
    db_session.add(rule)
    db_session.commit()

    assert evaluate_rules(db_session, message, analysis=None) == []
