from __future__ import annotations

from email.message import EmailMessage

from app.services.mail.imap_client import ImapConnector, parse_list_response


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


def test_parse_html_only_single_part_message_does_not_leak_raw_markup():
    # Reproduces a real report: OpenAI's account-notification emails (and
    # much other automated mail) are single-part text/html with no
    # multipart/alternative text/plain fallback. Before the fix, the
    # `else` branch in ImapConnector._parse blindly assigned the raw
    # decoded payload to body_text regardless of Content-Type, so the
    # message detail view rendered "<!DOCTYPE html><html>..." verbatim.
    msg = EmailMessage()
    msg["Subject"] = "New sign-in to your OpenAI account"
    msg["From"] = "OpenAI <noreply@tm.openai.com>"
    msg["Date"] = "Tue, 05 Aug 2025 10:00:00 +0900"
    msg.add_header("Content-Type", "text/html", charset="utf-8")
    msg.set_payload("<!DOCTYPE html><html><body><p>New sign-in detected.</p></body></html>", charset="utf-8")

    connector = ImapConnector(account=None)
    parsed = connector._parse("1", bytes(msg))

    assert "<html" not in parsed.body_text.lower()
    assert "<!doctype" not in parsed.body_text.lower()
    assert "New sign-in detected." in parsed.body_text
    assert "<html" in parsed.body_html.lower()


def test_parse_handles_missing_date_gracefully():
    msg = EmailMessage()
    msg["Subject"] = "件名のみ"
    msg["From"] = "a@b.com"
    msg.set_content("本文")

    connector = ImapConnector(account=None)
    parsed = connector._parse("1", bytes(msg))

    assert parsed.received_at is None
    assert parsed.subject == "件名のみ"


def test_parse_list_response_quoted_name():
    assert parse_list_response(rb'(\HasNoChildren) "/" "INBOX"') == "INBOX"


def test_parse_list_response_unquoted_name():
    assert parse_list_response(rb'(\HasNoChildren) "/" INBOX') == "INBOX"


def test_parse_list_response_nested_folder_with_slash_delimiter():
    assert parse_list_response(rb'(\HasNoChildren) "/" "[Gmail]/Sent Mail"') == "[Gmail]/Sent Mail"


def test_parse_list_response_nil_delimiter():
    assert parse_list_response(rb'(\Noselect) NIL "Trash"') == "Trash"


def test_parse_list_response_returns_none_for_malformed_line():
    assert parse_list_response(b"not a list response at all") is None


def test_parse_list_response_multiple_flags():
    assert parse_list_response(rb'(\Noselect \HasChildren) "/" "[Gmail]"') == "[Gmail]"
