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
import re
from dataclasses import dataclass
from email.header import decode_header
from email.utils import parsedate_to_datetime

from app.core.security import decrypt_secret
from app.db.models.email import EmailAccount
from app.services.mail.html_text import html_to_text

# Matches an IMAP LIST response line: (flags) "delimiter" name
# e.g. `(\HasNoChildren) "/" "INBOX"` or `(\Noselect \HasChildren) "/" INBOX`
# (name may or may not be quoted, delimiter may be NIL).
_LIST_RESPONSE_RE = re.compile(rb'^\(([^)]*)\)\s+("(?:[^"\\]|\\.)*"|NIL)\s+(.+)$')


def _decode_mailbox_name(raw: bytes) -> str:
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError:
        # Non-ASCII IMAP folder names use modified UTF-7 (RFC 3501), which
        # isn't implemented here — falling back to a lossy UTF-8 decode
        # keeps folder listing from crashing at the cost of possibly
        # mangled non-ASCII folder names.
        return raw.decode("utf-8", errors="replace")


def parse_list_response(raw: bytes) -> str | None:
    """Parses one line of an IMAP LIST response into a folder name, or None
    if the line doesn't match the expected shape (kept as a standalone
    function so it's testable without a real IMAP server)."""
    match = _LIST_RESPONSE_RE.match(raw)
    if not match:
        return None
    name_part = match.group(3).strip()
    if name_part.startswith(b'"') and name_part.endswith(b'"'):
        name_part = name_part[1:-1]
    return _decode_mailbox_name(name_part)


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

    def list_folders(self) -> list[str]:
        password = decrypt_secret(self.account.credential_encrypted) if self.account.credential_encrypted else ""
        conn_cls = imaplib.IMAP4_SSL if self.account.use_ssl else imaplib.IMAP4
        conn = conn_cls(self.account.imap_host, self.account.imap_port or (993 if self.account.use_ssl else 143))
        try:
            conn.login(self.account.email_address, password)
            status, data = conn.list()
            if status != "OK":
                return []
            names = [parse_list_response(raw) for raw in data if raw]
            return [name for name in names if name is not None]
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass

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
            # Single-part message: this used to always land in body_text
            # regardless of Content-Type, so an HTML-only message (no
            # multipart/alternative text/plain fallback — common for
            # automated notification mail) showed its raw markup
            # (<!DOCTYPE html>...) as if it were the message text.
            payload = (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", errors="replace")
            if msg.get_content_type() == "text/html":
                body_html = payload
            else:
                body_text = payload

        if not body_text and body_html:
            body_text = html_to_text(body_html)

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
