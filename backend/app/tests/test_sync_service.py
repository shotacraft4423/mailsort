"""Regression coverage: sync_account's "already imported?" dedup check
used to include Message.folder in the lookup key. Since Message.folder is
mutated locally after import (Archive/Trash actions, and classification-
based folder routing), re-syncing INBOX after moving a message out of it
made the message look new again and re-imported it as a duplicate — with
a redundant AI analysis job enqueued on top of the token cost that implies.
"""
from __future__ import annotations

import pytest

from app.db.models.email import EmailAccount, Message
from app.services.mail import sync_service
from app.services.mail.imap_client import FetchedMessage


def _fetched(uid: str, subject: str = "件名") -> FetchedMessage:
    return FetchedMessage(
        uid=uid,
        subject=subject,
        sender_name="送信者",
        sender_address="a@b.com",
        to_addresses=[],
        cc_addresses=[],
        body_text="本文",
        body_html="",
        received_at=None,
        attachments=[],
    )


@pytest.mark.asyncio
async def test_moving_a_synced_message_out_of_inbox_does_not_cause_a_reimport(db_session, monkeypatch):
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.commit()

    monkeypatch.setattr(
        "app.services.mail.imap_client.ImapConnector.fetch_new",
        lambda self, folder, limit: [_fetched("100")],
    )

    first_sync = await sync_service.sync_account(db_session, account, folder="INBOX")
    assert len(first_sync) == 1
    message_id = first_sync[0].id

    message = db_session.query(Message).filter(Message.id == message_id).one()
    message.folder = "Archive"  # what PATCH /mail/{id} does for the archive action
    db_session.commit()

    second_sync = await sync_service.sync_account(db_session, account, folder="INBOX")
    assert second_sync == []

    total = db_session.query(Message).filter(Message.account_id == account.id, Message.message_uid == "100").count()
    assert total == 1
    assert db_session.query(Message).filter(Message.id == message_id).one().folder == "Archive"
