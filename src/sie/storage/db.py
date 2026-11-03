"""Engine and session handling for PostgreSQL (production) and SQLite (fast unit tests)."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sie.config import get_settings


def make_engine(url: str, **kwargs) -> Engine:
    """Create an engine with sensible defaults per backend."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        kwargs.setdefault("connect_args", {"check_same_thread": False})
        if parsed.database in (None, "", ":memory:"):
            kwargs.setdefault("poolclass", StaticPool)  # one shared in-memory database
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record) -> None:
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        return engine
    kwargs.setdefault("pool_pre_ping", True)
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@lru_cache
def get_engine() -> Engine:
    return make_engine(get_settings().database_url)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_engine())


def reset_db_caches() -> None:
    """Dispose the cached engine and forget it (tests, config changes)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    """Transaction scope: commit on success, roll back on any exception, always close."""
    session = (factory or get_session_factory())()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def ping(engine: Engine | None = None) -> bool:
    """True if the database answers a trivial query."""
    try:
        with (engine or get_engine()).connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
