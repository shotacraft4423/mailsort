from __future__ import annotations

import email
import socket
from email import policy
from email.header import decode_header

import pytest
from aiosmtpd.controller import Controller

from app.db.models.email import EmailAccount
from app.services.mail import smtp_client


def _decode(value: str) -> str:
    parts = decode_header(value)
    return "".join(p.decode(enc or "utf-8") if isinstance(p, bytes) else p for p, enc in parts)


class _CapturingHandler:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def handle_DATA(self, server, session, envelope):  # noqa: N802 - aiosmtpd's required hook name
        self.messages.append(
            {
                "mail_from": envelope.mail_from,
                "rcpt_tos": envelope.rcpt_tos,
                "content": envelope.content.decode("utf-8", errors="replace"),
            }
        )
        return "250 Message accepted for delivery"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def smtp_server():
    handler = _CapturingHandler()
    port = _free_port()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield handler, port
    finally:
        controller.stop()


def test_send_message_delivers_to_local_smtp_server(smtp_server):
    handler, port = smtp_server

    account = EmailAccount(
        display_name="test",
        email_address="sales@mailsort.example",
        protocol="imap_smtp",
        smtp_host="127.0.0.1",
        smtp_port=port,
        use_ssl=False,
    )

    smtp_client.send_message(
        account,
        to=["buyer@example.com"],
        cc=["cc@example.com"],
        subject="Re: Java案件のご紹介",
        body_text="ご連絡ありがとうございます。詳細確認の上、改めてご連絡いたします。",
        in_reply_to="<original-message-id@vendor.example>",
    )

    assert len(handler.messages) == 1
    delivered = handler.messages[0]
    assert delivered["mail_from"] == "sales@mailsort.example"
    assert set(delivered["rcpt_tos"]) == {"buyer@example.com", "cc@example.com"}

    parsed = email.message_from_string(delivered["content"], policy=policy.default)
    assert _decode(parsed["Subject"]) == "Re: Java案件のご紹介"
    assert parsed["In-Reply-To"] == "<original-message-id@vendor.example>"
    assert "詳細確認の上" in parsed.get_content()
