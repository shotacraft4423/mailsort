"""Regression coverage: the folder-routing criteria were entirely
hardcoded in Python (analysis_service._CATEGORY_FOLDER_MAP), with no way
for a user to change what gets routed where or use a custom folder name.
The rule engine already had a GUI (conditions + actions) but only "tag"
was a real action — this adds "move_to_folder" so a user-defined rule can
route to any folder name, and it takes precedence over the built-in
heuristic since rules run after it.
"""
from __future__ import annotations

import json

import pytest

from app.db.models.email import EmailAccount, Message
from app.db.models.rule import Rule
from app.services import analysis_service, rule_engine


@pytest.mark.asyncio
async def test_move_to_folder_rule_overrides_the_builtin_heuristic(db_session):
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

    # Would otherwise land in the built-in "案件" folder — this rule sends
    # important-client mail to a custom folder name instead.
    rule = Rule(
        name="重要顧客専用フォルダ",
        is_active=True,
        priority=10,
        conditions_json=json.dumps([{"field": "sender_address", "operator": "contains", "value": "important-client"}]),
        actions_json=json.dumps([{"type": "move_to_folder", "params": {"folder": "最重要顧客"}}]),
    )
    db_session.add(rule)
    db_session.commit()

    await analysis_service.analyze_message(db_session, message)

    assert db_session.query(Message).filter(Message.id == message.id).one().folder == "最重要顧客"


def test_move_to_folder_action_is_a_noop_without_a_folder_param(db_session):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    message = Message(account_id=account.id, message_uid="1", subject="件名", sender_address="a@b.com", folder="INBOX")
    db_session.add(message)
    db_session.commit()

    result = rule_engine.RuleFireResult(
        rule=Rule(name="x", conditions_json="[]", actions_json="[]"),
        actions=[{"type": "move_to_folder", "params": {}}],
    )
    rule_engine.apply_actions(db_session, message, [result])

    assert message.folder == "INBOX"
