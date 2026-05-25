"""Database engine + session helpers.

Phase 1 is single-process SQLite (default path: ~/.hollerbox/hollerbox.sqlite,
in-memory in tests). The choice of `sessionmaker` keeps Phase 3's async
worker free to wrap calls in a thread-pool executor without rewriting any
store code.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from hollerbox.store.models import Base

DEFAULT_DATA_DIR = Path("~/.hollerbox").expanduser()
DEFAULT_DB_FILENAME = "hollerbox.sqlite"


def default_db_url() -> str:
    """Where the production SQLite file lives by default."""
    return f"sqlite:///{DEFAULT_DATA_DIR / DEFAULT_DB_FILENAME}"


def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine.

    For SQLite, foreign keys are off by default; we turn them on per
    connection so cascade behavior actually fires in tests and runtime.
    """
    db_url = url or default_db_url()
    if db_url.startswith("sqlite") and ":///" in db_url:
        # Ensure the parent dir exists for file-based sqlite.
        file_part = db_url.split(":///", 1)[1]
        if file_part and file_part != ":memory:":
            Path(file_part).expanduser().parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        db_url,
        echo=echo,
        future=True,
        connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {},
    )

    if db_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fks(dbapi_conn, _conn_record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all tables. Idempotent — safe to call on startup."""
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Context-managed session that commits on success, rolls back on error."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
