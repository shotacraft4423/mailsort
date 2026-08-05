"""Minimal subject-based thread grouping.

The Thread model existed from the start (db/models/email.py) but nothing
ever populated it — inbound sync never assigned a thread_id, and sent
replies weren't recorded as Messages at all. That meant "スレッド履歴"
(thread history, one of the spec's classification inputs) and any
reply-rate/response-speed insight had no data to work from.

This is intentionally simple: normalize away Re:/Fwd: prefixes and group by
(account_id, normalized subject). It will over-merge unrelated messages that
happen to share a subject and under-merge threads whose subject changed —
a real implementation would also match on References/In-Reply-To headers
(imap_client.py doesn't currently parse them). Good enough for reply-rate/
speed aggregates and thread listing; revisit if that proves too noisy.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.db.models.email import Thread

_PREFIX_RE = re.compile(r"^(re|fw|fwd)\s*[:：]\s*", re.IGNORECASE)


def normalize_subject(subject: str) -> str:
    normalized = (subject or "").strip()
    while True:
        stripped = _PREFIX_RE.sub("", normalized).strip()
        if stripped == normalized:
            break
        normalized = stripped
    return normalized or "(件名なし)"


def get_or_create_thread(db: Session, account_id: str, subject: str) -> Thread:
    normalized = normalize_subject(subject)
    thread = (
        db.query(Thread)
        .filter(Thread.account_id == account_id, Thread.subject_normalized == normalized)
        .one_or_none()
    )
    if thread is None:
        thread = Thread(account_id=account_id, subject_normalized=normalized)
        db.add(thread)
        db.flush()
    return thread
