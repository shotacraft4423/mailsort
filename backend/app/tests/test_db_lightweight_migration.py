"""Regression coverage for a real production failure: Base.metadata.
create_all() only creates tables that don't exist yet — it never alters an
existing table. A user whose mailsort.db was created before
Meeting.is_hidden was added to the model got
"sqlite3.OperationalError: no such column: meetings.is_hidden" on every
query touching Meeting (message detail's related-data panel, the meetings
list, dashboard reminders), because the column genuinely didn't exist in
their file. init_db() now ALTERs in any column a model declares that an
existing table is missing, and backfills NULLs to the model's declared
default (important for boolean flags queried with `.is_(False)`, which
NULL does not satisfy).
"""
from __future__ import annotations

import tempfile

from sqlalchemy import create_engine, inspect, text

import app.db.session as db_session_module
from app.db.base import Base


def test_add_missing_columns_patches_an_old_table_and_backfills_default(monkeypatch):
    db_path = tempfile.mktemp(suffix=".db")
    old_style_engine = create_engine(f"sqlite:///{db_path}")

    # Simulate a mailsort.db created before Meeting.is_hidden existed:
    # every real column except that one, plus one pre-existing row.
    with old_style_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE meetings (
                    id VARCHAR(36) PRIMARY KEY,
                    created_at DATETIME,
                    updated_at DATETIME,
                    source_message_id VARCHAR(36),
                    company_id VARCHAR(36),
                    title VARCHAR(500),
                    platform VARCHAR(32),
                    join_url TEXT,
                    platform_link_hash VARCHAR(64),
                    starts_at DATETIME,
                    ends_at DATETIME,
                    participants_json TEXT,
                    is_rescheduled BOOLEAN,
                    supersedes_meeting_id VARCHAR(36)
                )
                """
            )
        )
        conn.execute(
            text("INSERT INTO meetings (id, title, platform, join_url) VALUES ('m1', 'キックオフ', 'meet', 'https://meet.example/x')")
        )

    import app.db.models  # noqa: F401 ensure every model (including Meeting) is registered

    monkeypatch.setattr(db_session_module, "engine", old_style_engine)
    db_session_module.init_db()

    inspector = inspect(old_style_engine)
    columns = {col["name"] for col in inspector.get_columns("meetings")}
    assert "is_hidden" in columns

    with old_style_engine.connect() as conn:
        row = conn.execute(text("SELECT is_hidden FROM meetings WHERE id = 'm1'")).one()
        assert row[0] == 0  # backfilled to the model's default (False), not left NULL

    Meeting = Base.registry._class_registry["Meeting"]
    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=old_style_engine)()
    try:
        # The exact query that crashed in production: filtering on
        # is_hidden for a row that predates the column.
        assert session.query(Meeting).filter(Meeting.is_hidden.is_(False)).count() == 1
    finally:
        session.close()
