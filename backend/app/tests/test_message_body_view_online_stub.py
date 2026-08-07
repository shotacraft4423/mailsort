"""Real user report: a message rendered fully in Outlook but showed almost
nothing in MailSort ("このようにうまく表示されないメールがある"). Root
cause: mass-mail ASPs (cuenote and similar) commonly send a
multipart/alternative message whose text/plain part is intentionally just a
one-or-two-line "メールがうまく表示されない方はこちらをご覧ください" stub
with a tracking link, while the actual content only exists in the text/html
part. imap_client correctly stores both parts, but GET /mail/{id} only ever
displayed body_text, so the mail looked empty/broken even though body_html
had the real content the whole time. See _display_body_text in
api/routes/mail.py."""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient


def _make_client() -> TestClient:
    os.environ["MAILSORT_DATABASE_URL"] = f"sqlite:///{tempfile.mktemp(suffix='.db')}"
    os.environ["MAILSORT_DATA_DIR"] = tempfile.mkdtemp()
    from app.main import app

    return TestClient(app)


_STUB_TEXT = "メールがうまく表示されない方はこちらをご覧ください\nhttps://gy53.asp.cuenote.jp/h/X8PcqyuNulM60XbaYo"

_RICH_HTML = """
<html><body>
<p>創意ラボ株式会社</p>
<p>営業ご担当者様</p>
<p>お世話になっております。株式会社D-Standingの濱田でございます。</p>
<p>下記、案件にて人材を募集しております。見合う人材がいらっしゃいましたら、ご提案をお待ちしております。</p>
<p>◆ 管理ID：HMD0100005</p>
<p>◆ 案件：大手放送局グループのデジタルエンターテインメント企業におけるAIスペシャリスト</p>
<p>◆ 必須スキル：AIに関する特定の領域で高い専門性</p>
<p>◆ 年齢：〜50歳</p>
</body></html>
"""


def test_get_message_prefers_html_derived_text_over_a_view_online_stub():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(
            account_id=account.id,
            message_uid="1",
            subject="【エンド直】生成AI/リモート可",
            sender_address="dss@d-standing.co.jp",
            body_text=_STUB_TEXT,
            body_html=_RICH_HTML,
        )
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}")
        assert resp.status_code == 200
        body_text = resp.json()["body_text"]
        assert "AIスペシャリスト" in body_text
        assert "HMD0100005" in body_text


def test_get_message_leaves_a_normal_plain_text_body_alone_even_with_html_present():
    with _make_client() as client:
        from app.db.session import SessionLocal
        from app.db.models.email import EmailAccount, Message

        db = SessionLocal()
        account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
        db.add(account)
        db.flush()
        message = Message(
            account_id=account.id,
            message_uid="1",
            subject="件名",
            sender_address="a@b.com",
            body_text="こんにちは、案件のご紹介です。ご確認のほどよろしくお願いいたします。",
            body_html="<html><body><p>こんにちは、案件のご紹介です。ご確認のほどよろしくお願いいたします。</p></body></html>",
        )
        db.add(message)
        db.commit()
        message_id = message.id
        db.close()

        resp = client.get(f"/mail/{message_id}")
        assert resp.json()["body_text"] == "こんにちは、案件のご紹介です。ご確認のほどよろしくお願いいたします。"
