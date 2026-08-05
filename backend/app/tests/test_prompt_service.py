from __future__ import annotations

from app.db.models.ai import PromptTemplate, PromptVersion
from app.db.models.email import EmailAccount, Message
from app.services import classification_service
from app.services.prompt_service import get_active_prompt, render_template


def test_render_template_substitutes_known_variables_and_leaves_unknown_blank():
    rendered = render_template("件名: {{ subject }} / 不明: {{ missing }}", {"subject": "テスト"})
    assert rendered == "件名: テスト / 不明: "


def test_get_active_prompt_returns_none_when_no_template_exists(db_session):
    assert get_active_prompt(db_session, "classification") is None


def test_get_active_prompt_returns_active_version(db_session):
    template = PromptTemplate(name="カスタム分類", task="classification", is_active=True)
    db_session.add(template)
    db_session.flush()

    version = PromptVersion(
        template_id=template.id,
        version_number=1,
        system_prompt="カスタムシステムプロンプト",
        user_prompt_template="件名のみ: {{ subject }}",
    )
    db_session.add(version)
    db_session.flush()
    template.active_version_id = version.id
    db_session.commit()

    active = get_active_prompt(db_session, "classification")
    assert active is not None
    assert active.system_prompt == "カスタムシステムプロンプト"


async def test_classify_message_uses_custom_active_prompt(db_session):
    template = PromptTemplate(name="カスタム分類", task="classification", is_active=True)
    db_session.add(template)
    db_session.flush()

    version = PromptVersion(
        template_id=template.id,
        version_number=1,
        system_prompt="カスタムシステムプロンプト",
        user_prompt_template="対象メール件名: {{ subject }}\n本文: {{ body }}",
    )
    db_session.add(version)
    db_session.flush()
    template.active_version_id = version.id

    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()

    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="人材のご紹介です",
        sender_address="sales@vendor.example",
        body_text="人材のご紹介です。ご確認ください。",
    )
    db_session.add(message)
    db_session.commit()

    outcome = await classification_service.classify_message(db_session, message)
    assert outcome.analysis.prompt_template_id == template.id
