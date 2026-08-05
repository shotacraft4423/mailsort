from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _isolated_sqlite_db(monkeypatch):
    """Every test gets its own throwaway SQLite file so tests don't leak
    state into each other or into the developer's real mailsort.db."""
    db_path = tempfile.mktemp(suffix=".db")
    monkeypatch.setenv("MAILSORT_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MAILSORT_AI_ENABLED", "true")
    monkeypatch.setenv("MAILSORT_LLM_PROVIDER", "local_mock")
    monkeypatch.setenv("MAILSORT_EMBEDDING_PROVIDER", "local_mock")

    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def db_session():
    from app.core.config import get_settings
    from app.db.base import Base
    from app.db.session import _make_engine

    import app.db.models  # noqa: F401

    engine = _make_engine()
    Base.metadata.create_all(bind=engine)

    from sqlalchemy.orm import sessionmaker

    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
