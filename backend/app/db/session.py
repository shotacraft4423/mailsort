from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base


def _make_engine():
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables, then patch in any columns added to a model since
    the table was first created. SQLite-friendly; a real deployment would
    use Alembic migrations."""
    import app.db.models  # noqa: F401  ensure models are registered on Base.metadata

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all() only creates tables that don't exist yet — it never
    alters an existing table, so a user whose mailsort.db predates a
    column added to a model later (e.g. Meeting.is_hidden) got
    'sqlite3.OperationalError: no such column' on every query touching it,
    crashing message detail/related-data/dashboard/meetings endpoints.
    This inspects each already-existing table's real columns and ALTERs in
    whatever the model declares that the table doesn't have, then backfills
    NULLs in the new column to the model's default (ADD COLUMN always
    leaves existing rows NULL regardless of the Python-side default,
    which matters for boolean flags like is_hidden that are filtered with
    `.is_(False)` — NULL doesn't satisfy that and would make every
    pre-existing row look filtered-out).
    """
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue  # brand-new table; create_all() already created it with every column
        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
        missing = [c for c in table.columns if c.name not in existing_columns]
        if not missing:
            continue
        with engine.begin() as conn:
            for column in missing:
                col_type = column.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                _backfill_default(conn, table.name, column)


def _backfill_default(conn, table_name: str, column) -> None:
    default = column.default
    if default is None or default.is_callable or default.is_sequence or default.is_clause_element:
        return  # no static default to backfill (or it's dynamic, e.g. UUIDs/timestamps — leaving NULL is fine there)
    value = default.arg
    if isinstance(value, bool):
        conn.execute(text(f'UPDATE "{table_name}" SET "{column.name}" = :v WHERE "{column.name}" IS NULL'), {"v": int(value)})
    elif isinstance(value, (int, float, str)):
        conn.execute(text(f'UPDATE "{table_name}" SET "{column.name}" = :v WHERE "{column.name}" IS NULL'), {"v": value})


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
