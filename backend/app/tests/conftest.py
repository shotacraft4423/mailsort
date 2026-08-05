from __future__ import annotations

import os
import shutil
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _isolated_sqlite_db(monkeypatch):
    """Every test gets its own throwaway SQLite file and data_dir so tests
    don't leak state into each other, into the developer's real
    mailsort.db, or (since core/security.py persists the encryption key
    under data_dir) into the developer's real ~/.mailsort/secret.key."""
    db_path = tempfile.mktemp(suffix=".db")
    data_dir = tempfile.mkdtemp(prefix="mailsort-test-")
    monkeypatch.setenv("MAILSORT_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MAILSORT_DATA_DIR", data_dir)
    monkeypatch.setenv("MAILSORT_AI_ENABLED", "true")
    monkeypatch.setenv("MAILSORT_LLM_PROVIDER", "local_mock")
    monkeypatch.setenv("MAILSORT_EMBEDDING_PROVIDER", "local_mock")
    monkeypatch.delenv("MAILSORT_SECRET_KEY", raising=False)

    from app.core.config import get_settings

    get_settings.cache_clear()

    # app.db.session.engine/SessionLocal are module-level singletons bound
    # once at first import. Without rebinding them here, any test that goes
    # through `TestClient(app)` (rather than the db_session fixture below,
    # which always builds its own fresh engine) would silently share one
    # database across the entire pytest session regardless of the env vars
    # just set above — a real bug caught by test_send_reply_persistence.py
    # once a second TestClient-based test file existed.
    import app.db.session as db_session_module
    from sqlalchemy.orm import sessionmaker as _sessionmaker

    db_session_module.engine = db_session_module._make_engine()
    db_session_module.SessionLocal = _sessionmaker(bind=db_session_module.engine, autoflush=False, autocommit=False)

    yield
    get_settings.cache_clear()
    if os.path.exists(db_path):
        os.remove(db_path)
    shutil.rmtree(data_dir, ignore_errors=True)


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
