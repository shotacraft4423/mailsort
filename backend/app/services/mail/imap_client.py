"""Generic IMAP connector (stdlib `imaplib`, no extra dependency). Covers
any IMAP host including Gmail (imap.gmail.com with an app password or
OAuth2 XOAUTH2 token) and Microsoft365/Exchange (outlook.office365.com).
Gmail API / Microsoft Graph (richer than IMAP: push notifications, better
threading) are Phase 2 dedicated connectors sharing the same
`MailConnector` protocol so sync_service.py doesn't need to know which one
it's talking to.
"""
from __future__ import annotations

import email
import imaplib
from dataclasses import dataclass
from email.header import decode_header
from email.utils import parsedate_to_datetime

from app.core.security import decrypt_secret
from app.db.models.email import EmailAccount


@dataclass
class FetchedMessage:
    uid: str
    subject: str
    sender_name: str
    sender_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    body_text: str
    body_html: str
    received_at: str | None
    attachments: list[tuple[str, str, bytes]]  # (filename, content_type, data)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    return "".join(
        (part.decode(encoding or "utf-8", errors="replace") if isinstance(part, bytes) else part) for part, encoding in parts
    )


class ImapConnector:
    """Thin synchronous wrapper; sync_service.py runs it in a worker thread
    via asyncio.to_thread so it never blocks the FastAPI event loop."""

    def __init__(self, account: EmailAccount) -> None:
        self.account = account

    def fetch_new(self, folder: str = "INBOX", limit: int = 50) -> list[FetchedMessage]:
        password = decrypt_secret(self.account.credential_encrypted) if self.account.credential_encrypted else ""
        conn_cls = imaplib.IMAP4_SSL if self.account.use_ssl else imaplib.IMAP4
        conn = conn_cls(self.account.imap_host, self.account.imap_port or (993 if self.account.use_ssl else 143))
        try:
            conn.login(self.account.email_address, password)
            conn.select(folder)
            status, data = conn.search(None, "ALL")
            if status != "OK":
                return []
            uids = data[0].split()[-limit:]

            messages = []
            for uid in uids:
                status, msg_data = conn.fetch(uid, "(RFC822)")
                if status != "OK" or not msg_data or msg_data[0] is None:
                    continue
                raw = msg_data[0][1]
                messages.append(self._parse(uid.decode(), raw))
            return messages
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass

    def _parse(self, uid: str, raw: bytes) -> FetchedMessage:
        msg = email.message_from_bytes(raw)
        body_text, body_html, attachments = "", "", []

        if msg.is_multipart():
            for part in msg.walk():
                disposition = str(part.get("Content-Disposition", ""))
                content_type = part.get_content_type()
                if "attachment" in disposition:
                    filename = _decode(part.get_filename())
                    payload = part.get_payload(decode=True) or b""
                    attachments.append((filename, content_type, payload))
                elif content_type == "text/plain" and not body_text:
                    body_text = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="replace")
                elif content_type == "text/html" and not body_html:
                    body_html = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="replace")
        else:
            payload = msg.get_payload(decode=True) or b""
            body_text = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

        received_at = None
        if msg.get("Date"):
            try:
                received_at = parsedate_to_datetime(msg["Date"]).isoformat()
            except (TypeError, ValueError):
                received_at = None

        from_header = _decode(msg.get("From"))
        sender_name, sender_address = email.utils.parseaddr(from_header)

        return FetchedMessage(
            uid=uid,
            subject=_decode(msg.get("Subject")),
            sender_name=sender_name,
            sender_address=sender_address,
            to_addresses=[addr for _, addr in email.utils.getaddresses([msg.get("To", "")])],
            cc_addresses=[addr for _, addr in email.utils.getaddresses([msg.get("Cc", "")])],
            body_text=body_text,
            body_html=body_html,
            received_at=received_at,
            attachments=attachments,
        )
