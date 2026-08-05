from __future__ import annotations

from email.message import EmailMessage

from app.services.mail.imap_client import ImapConnector


def _build_raw_message() -> bytes:
    msg = EmailMessage()
    msg["Subject"] = "Java案件のご紹介"
    msg["From"] = "営業太郎 <sales@vendor.example>"
    msg["To"] = "buyer@example.com"
    msg["Cc"] = "cc1@example.com, cc2@example.com"
    msg["Date"] = "Tue, 05 Aug 2025 10:00:00 +0900"
    msg.set_content("本文はプレーンテキストです。ご確認ください。")
    msg.add_alternative("<p>本文はHTMLです。</p>", subtype="html")
    msg.add_attachment(
        b"dummy-bytes",
        maintype="application",
        subtype="pdf",
        filename="skill_sheet.pdf",
    )
    return bytes(msg)


def test_parse_extracts_subject_sender_body_and_attachment():
    connector = ImapConnector(account=None)  # _parse() never touches self.account
    parsed = connector._parse("123", _build_raw_message())

    assert parsed.uid == "123"
    assert parsed.subject == "Java案件のご紹介"
    assert parsed.sender_name == "営業太郎"
    assert parsed.sender_address == "sales@vendor.example"
    assert parsed.cc_addresses == ["cc1@example.com", "cc2@example.com"]
    assert "プレーンテキスト" in parsed.body_text
    assert "HTML" in parsed.body_html
    assert parsed.received_at is not None

    assert len(parsed.attachments) == 1
    filename, content_type, data = parsed.attachments[0]
    assert filename == "skill_sheet.pdf"
    assert content_type == "application/pdf"
    assert data == b"dummy-bytes"


def test_parse_handles_missing_date_gracefully():
    msg = EmailMessage()
    msg["Subject"] = "件名のみ"
    msg["From"] = "a@b.com"
    msg.set_content("本文")

    connector = ImapConnector(account=None)
    parsed = connector._parse("1", bytes(msg))

    assert parsed.received_at is None
    assert parsed.subject == "件名のみ"
