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


def test_fetch_new_skips_a_message_that_fails_to_parse_instead_of_returning_nothing(monkeypatch):
    """Real user report: "サーバーによって受信できないメールがある / 一件も
    受信できない" — one malformed message anywhere in the fetch window (an
    unusual header, a corrupt attachment MIME part, whatever) used to raise
    out of fetch_new()'s per-UID loop entirely. Since fetch_new() only ever
    returns its `messages` list at the very end, sync_account got nothing
    back at all for the whole batch — not just the one bad message, every
    other message waiting on that account, silently, with no error surfaced
    anywhere the user would see it. One bad message must not blank out an
    otherwise-successful sync."""
    from app.db.models.email import EmailAccount
    from app.services.mail.imap_client import FetchedMessage

    account = EmailAccount(
        display_name="a", email_address="a@example.com", protocol="imap_smtp",
        imap_host="imap.example.com", imap_port=993, use_ssl=True,
    )

    class _FakeConn:
        def login(self, *args, **kwargs):
            pass

        def select(self, folder):
            pass

        def search(self, charset, criteria):
            return "OK", [b"1 2 3"]

        def fetch(self, uid, spec):
            return "OK", [(b"1 (RFC822 {3}", uid + b"-raw")]

        def logout(self):
            pass

    monkeypatch.setattr("app.services.mail.imap_client.imaplib.IMAP4_SSL", lambda host, port: _FakeConn())

    def _parse(self, uid, raw):
        if uid == "2":
            raise ValueError("simulated malformed message")
        return FetchedMessage(
            uid=uid, subject="s", sender_name="n", sender_address="a@b.com",
            to_addresses=[], cc_addresses=[], body_text="body", body_html="",
            received_at=None, attachments=[],
        )

    monkeypatch.setattr(ImapConnector, "_parse", _parse)

    connector = ImapConnector(account)
    result = connector.fetch_new("INBOX", limit=50)

    assert [m.uid for m in result] == ["1", "3"]


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
