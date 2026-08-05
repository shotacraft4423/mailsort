"""Generic SMTP sender (stdlib `smtplib`). Same host coverage note as
imap_client.py."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.security import decrypt_secret
from app.db.models.email import EmailAccount


def send_message(
    account: EmailAccount,
    *,
    to: list[str],
    cc: list[str] | None,
    subject: str,
    body_text: str,
    in_reply_to: str | None = None,
) -> None:
    password = decrypt_secret(account.credential_encrypted) if account.credential_encrypted else ""

    msg = EmailMessage()
    msg["From"] = account.email_address
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body_text)

    host = account.smtp_host
    port = account.smtp_port or (465 if account.use_ssl else 587)

    server_cls = smtplib.SMTP_SSL if account.use_ssl else smtplib.SMTP
    with server_cls(host, port) as server:
        server.ehlo()
        # Only negotiate STARTTLS/AUTH when the server actually advertises
        # them: real 587/465 mail providers always do, but this keeps the
        # client usable against a plain internal relay too (and is what
        # makes it testable against a bare aiosmtpd instance, see
        # tests/test_smtp_client.py).
        if not account.use_ssl and server.has_extn("starttls"):
            server.starttls()
            server.ehlo()
        if password and server.has_extn("auth"):
            server.login(account.email_address, password)
        server.send_message(msg)
