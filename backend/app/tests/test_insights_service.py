from __future__ import annotations

from datetime import datetime, timedelta

from app.db.models.deal import Deal
from app.db.models.email import EmailAccount, Message, Thread
from app.services.insights_service import compute_insights


def _account(db_session) -> EmailAccount:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    return account


def test_reply_rate_and_speed_for_a_replied_thread(db_session):
    account = _account(db_session)
    thread = Thread(account_id=account.id, subject_normalized="Java案件")
    db_session.add(thread)
    db_session.flush()

    received = datetime(2026, 8, 1, 9, 0, 0)
    db_session.add(
        Message(
            account_id=account.id,
            thread_id=thread.id,
            folder="INBOX",
            message_uid="1",
            subject="Java案件のご紹介",
            sender_address="vendor@example.com",
            received_at=received,
        )
    )
    db_session.add(
        Message(
            account_id=account.id,
            thread_id=thread.id,
            folder="Sent",
            message_uid="sent-1",
            subject="Re: Java案件のご紹介",
            sender_address="me@example.com",
            received_at=received + timedelta(hours=3),
        )
    )
    db_session.commit()

    insights = compute_insights(db_session)
    assert insights.threads_with_inbound == 1
    assert insights.threads_replied == 1
    assert insights.reply_rate == 1.0
    assert insights.avg_reply_speed_hours == 3.0


def test_reply_rate_is_zero_when_no_thread_was_replied_to(db_session):
    account = _account(db_session)
    thread = Thread(account_id=account.id, subject_normalized="人材のご紹介")
    db_session.add(thread)
    db_session.flush()
    db_session.add(
        Message(
            account_id=account.id,
            thread_id=thread.id,
            folder="INBOX",
            message_uid="1",
            subject="人材のご紹介",
            sender_address="vendor@example.com",
            received_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    insights = compute_insights(db_session)
    assert insights.threads_with_inbound == 1
    assert insights.threads_replied == 0
    assert insights.reply_rate == 0.0
    assert insights.avg_reply_speed_hours is None


def test_reply_rate_is_none_when_no_threads_exist(db_session):
    insights = compute_insights(db_session)
    assert insights.reply_rate is None
    assert insights.avg_reply_speed_hours is None


def test_deal_win_rate_only_counts_resolved_deals(db_session):
    db_session.add_all(
        [
            Deal(title="filled deal", status="filled"),
            Deal(title="closed deal", status="closed"),
            Deal(title="still open deal", status="open"),
        ]
    )
    db_session.commit()

    insights = compute_insights(db_session)
    assert insights.deal_win_rate == 0.5  # 1 filled / (1 filled + 1 closed), open deal excluded


def test_deal_win_rate_is_none_when_no_resolved_deals(db_session):
    db_session.add(Deal(title="still open deal", status="open"))
    db_session.commit()

    insights = compute_insights(db_session)
    assert insights.deal_win_rate is None


def test_weekly_contact_frequency_counts_recent_messages_only(db_session):
    account = _account(db_session)
    now = datetime.utcnow()
    db_session.add_all(
        [
            Message(account_id=account.id, folder="INBOX", message_uid="recent", subject="x", sender_address="a@b.com", received_at=now),
            Message(
                account_id=account.id,
                folder="INBOX",
                message_uid="old",
                subject="x",
                sender_address="a@b.com",
                received_at=now - timedelta(weeks=52),
            ),
        ]
    )
    db_session.commit()

    insights = compute_insights(db_session, weeks_for_frequency=8)
    assert insights.weekly_contact_frequency == 1 / 8
