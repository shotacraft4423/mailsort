from __future__ import annotations

import json

from app.db.models.email import EmailAccount, Message
from app.db.models.rule import Rule
from app.services.rule_engine import evaluate_rules


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
