"""database_url used to default to the CWD-relative "sqlite:///./mailsort.db"
— fine by convention when everyone launched uvicorn from backend/, but a
packaged app (Tauri sidecar launching a PyInstaller-frozen exe) has no
guaranteed, writable current directory. It now resolves to a path under
data_dir instead, unless MAILSORT_DATABASE_URL is set explicitly."""
from __future__ import annotations

from app.core.config import Settings


def test_database_url_defaults_to_a_path_under_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("MAILSORT_DATABASE_URL", raising=False)
    data_dir = tmp_path / "mailsort-data"

    settings = Settings(data_dir=data_dir)

    assert settings.database_url == f"sqlite:///{(data_dir / 'mailsort.db').as_posix()}"
    assert data_dir.exists()


def test_explicit_database_url_env_var_is_not_overridden(tmp_path, monkeypatch):
    monkeypatch.setenv("MAILSORT_DATABASE_URL", "sqlite:///:memory:")

    settings = Settings(data_dir=tmp_path / "mailsort-data")

    assert settings.database_url == "sqlite:///:memory:"
