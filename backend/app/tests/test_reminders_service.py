from __future__ import annotations

import json
from datetime import datetime, timedelta

from app.db.models.ai import AIAnalysis
from app.db.models.deal import Deal
from app.db.models.email import EmailAccount, Message, Thread
from app.db.models.meeting import Meeting
from app.services.insights_service import compute_reminders


def _account(db_session) -> EmailAccount:
    account = EmailAccount(display_name="a", email_address="a@example.com", protocol="imap_smtp")
    db_session.add(account)
    db_session.flush()
    return account


def test_overdue_reply_required_message_with_no_reply_is_flagged(db_session):
    account = _account(db_session)
    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="至急ご確認ください",
        sender_address="vendor@example.com",
        received_at=datetime.utcnow() - timedelta(hours=48),
    )
    db_session.add(message)
    db_session.flush()
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="x",
            provider_used="local_mock",
            classification_json=json.dumps({"reply_required": True}),
        )
    )
    db_session.commit()

    reminders = compute_reminders(db_session, overdue_reply_hours=24)
    assert len(reminders.overdue_replies) == 1
    assert reminders.overdue_replies[0].message_id == message.id
    assert reminders.overdue_replies[0].hours_overdue > 0


def test_message_already_replied_to_is_not_overdue(db_session):
    account = _account(db_session)
    thread = Thread(account_id=account.id, subject_normalized="件名")
    db_session.add(thread)
    db_session.flush()

    received = datetime.utcnow() - timedelta(hours=48)
    message = Message(
        account_id=account.id,
        thread_id=thread.id,
        message_uid="1",
        subject="件名",
        sender_address="vendor@example.com",
        received_at=received,
    )
    db_session.add(message)
    db_session.flush()
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="x",
            provider_used="local_mock",
            classification_json=json.dumps({"reply_required": True}),
        )
    )
    db_session.add(
        Message(
            account_id=account.id,
            thread_id=thread.id,
            folder="Sent",
            message_uid="sent-1",
            subject="Re: 件名",
            sender_address="me@example.com",
            received_at=received + timedelta(hours=1),
        )
    )
    db_session.commit()

    reminders = compute_reminders(db_session, overdue_reply_hours=24)
    assert reminders.overdue_replies == []


def test_recent_message_is_not_yet_overdue(db_session):
    account = _account(db_session)
    message = Message(
        account_id=account.id,
        message_uid="1",
        subject="件名",
        sender_address="vendor@example.com",
        received_at=datetime.utcnow() - timedelta(hours=1),
    )
    db_session.add(message)
    db_session.flush()
    db_session.add(
        AIAnalysis(
            message_id=message.id,
            content_hash="x",
            provider_used="local_mock",
            classification_json=json.dumps({"reply_required": True}),
        )
    )
    db_session.commit()

    reminders = compute_reminders(db_session, overdue_reply_hours=24)
    assert reminders.overdue_replies == []


def test_upcoming_meeting_within_window_is_included(db_session):
    db_session.add(
        Meeting(title="キックオフ", platform="teams", join_url="https://teams.example/x", starts_at=datetime.utcnow() + timedelta(days=2))
    )
    db_session.commit()

    reminders = compute_reminders(db_session, upcoming_meeting_days=7)
    assert len(reminders.upcoming_meetings) == 1
    assert reminders.upcoming_meetings[0].title == "キックオフ"


def test_meeting_outside_window_is_excluded(db_session):
    db_session.add(
        Meeting(title="遠い先の会議", platform="zoom", join_url="https://zoom.example/x", starts_at=datetime.utcnow() + timedelta(days=30))
    )
    db_session.commit()

    reminders = compute_reminders(db_session, upcoming_meeting_days=7)
    assert reminders.upcoming_meetings == []


def test_hidden_meeting_is_excluded_from_upcoming_reminders(db_session):
    db_session.add(
        Meeting(
            title="非表示にした会議",
            platform="zoom",
            join_url="https://zoom.example/hidden",
            starts_at=datetime.utcnow() + timedelta(days=2),
            is_hidden=True,
        )
    )
    db_session.commit()

    reminders = compute_reminders(db_session, upcoming_meeting_days=7)
    assert reminders.upcoming_meetings == []


def test_upcoming_meeting_carries_source_message_id_for_dashboard_click_through(db_session):
    account = _account(db_session)
    message = Message(account_id=account.id, message_uid="1", subject="MTG案内", sender_address="a@b.com")
    db_session.add(message)
    db_session.flush()
    db_session.add(
        Meeting(
            title="キックオフ",
            platform="teams",
            join_url="https://teams.example/x",
            starts_at=datetime.utcnow() + timedelta(days=2),
            source_message_id=message.id,
        )
    )
    db_session.commit()

    reminders = compute_reminders(db_session, upcoming_meeting_days=7)
    assert reminders.upcoming_meetings[0].source_message_id == message.id


def test_expiring_deal_with_passed_reply_deadline_is_flagged(db_session):
    db_session.add(
        Deal(title="Java案件", status="open", reply_deadline=(datetime.utcnow() - timedelta(days=3)).date())
    )
    db_session.commit()

    reminders = compute_reminders(db_session)
    assert len(reminders.expiring_deals) == 1
    assert reminders.expiring_deals[0].days_overdue == 3


def test_expiring_deal_carries_source_message_id_for_dashboard_click_through(db_session):
    account = _account(db_session)
    message = Message(account_id=account.id, message_uid="1", subject="案件のご紹介", sender_address="a@b.com")
    db_session.add(message)
    db_session.flush()
    db_session.add(
        Deal(
            title="Java案件",
            status="open",
            reply_deadline=(datetime.utcnow() - timedelta(days=3)).date(),
            source_message_id=message.id,
        )
    )
    db_session.commit()

    reminders = compute_reminders(db_session)
    assert reminders.expiring_deals[0].source_message_id == message.id


def test_closed_deal_is_not_flagged_as_expiring(db_session):
    db_session.add(
        Deal(title="Java案件", status="closed", reply_deadline=(datetime.utcnow() - timedelta(days=3)).date())
    )
    db_session.commit()

    reminders = compute_reminders(db_session)
    assert reminders.expiring_deals == []


def test_recommended_actions_merges_and_sorts_by_urgency(db_session):
    db_session.add(Deal(title="超過案件", status="open", reply_deadline=(datetime.utcnow() - timedelta(days=10)).date()))
    db_session.add(
        Meeting(title="今日の会議", platform="teams", join_url="https://teams.example/x", starts_at=datetime.utcnow() + timedelta(hours=1))
    )
    db_session.commit()

    reminders = compute_reminders(db_session)
    kinds = [a.kind for a in reminders.recommended_actions]
    assert "deal" in kinds
    assert "meeting" in kinds
    # sorted descending by urgency_score
    scores = [a.urgency_score for a in reminders.recommended_actions]
    assert scores == sorted(scores, reverse=True)
