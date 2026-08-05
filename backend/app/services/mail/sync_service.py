"""Pulls new mail via ImapConnector, writes Message/Attachment rows, and
enqueues AI analysis jobs. Runs the blocking IMAP call in a worker thread so
it doesn't stall the FastAPI event loop; DB writes are AI-independent so a
sync succeeds even with AI disabled or an API outage — AI jobs just sit in
the queue until a provider is reachable.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models.email import Attachment, EmailAccount, Message
from app.services import queue
from app.services.mail.imap_client import FetchedMessage, ImapConnector


async def sync_account(db: Session, account: EmailAccount, *, folder: str = "INBOX", limit: int = 50) -> list[Message]:
    connector = ImapConnector(account)
    fetched = await asyncio.to_thread(connector.fetch_new, folder, limit)

    created: list[Message] = []
    for item in fetched:
        exists = (
            db.query(Message)
            .filter(Message.account_id == account.id, Message.message_uid == item.uid, Message.folder == folder)
            .one_or_none()
        )
        if exists:
            continue

        message = _to_message(account.id, folder, item)
        db.add(message)
        db.flush()

        for filename, content_type, data in item.attachments:
            db.add(
                Attachment(
                    message_id=message.id,
                    file_name=filename or "attachment",
                    content_type=content_type,
                    size_bytes=len(data),
                )
            )

        db.commit()
        db.refresh(message)
        created.append(message)

        queue.enqueue(db, message.id, "classify")
        queue.enqueue(db, message.id, "extract")

    return created


def _to_message(account_id: str, folder: str, item: FetchedMessage) -> Message:
    received_at = datetime.fromisoformat(item.received_at) if item.received_at else None
    return Message(
        account_id=account_id,
        folder=folder,
        message_uid=item.uid,
        subject=item.subject,
        sender_name=item.sender_name,
        sender_address=item.sender_address,
        to_addresses=_json_list(item.to_addresses),
        cc_addresses=_json_list(item.cc_addresses),
        body_text=item.body_text,
        body_html=item.body_html,
        received_at=received_at,
    )


def _json_list(values: list[str]) -> str:
    import json

    return json.dumps(values, ensure_ascii=False)
