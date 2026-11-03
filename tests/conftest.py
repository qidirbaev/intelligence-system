import os
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from sie.config import DEV_DATABASE_URL, clear_settings_cache
from sie.storage import migrate
from sie.storage.db import make_engine, make_session_factory, reset_db_caches

_ENV_PREFIXES = ("SIE_",)
_ENV_NAMES = ("DATABASE_URL", "TELEGRAM_API_ID", "TELEGRAM_API_HASH")
_KEEP = {"SIE_TEST_DATABASE_URL"}  # test-infrastructure setting, not application config

ALL_TABLES = "persons, sources, access_basis, agent_state, policy_versions, audit_log"


def _base_pg_url() -> str:
    return os.environ.get("SIE_TEST_DATABASE_URL", DEV_DATABASE_URL)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """Every test starts without SIE settings in the environment and with empty caches."""
    for name in list(os.environ):
        if name in _KEEP:
            continue
        if name.startswith(_ENV_PREFIXES) or name in _ENV_NAMES:
            monkeypatch.delenv(name, raising=False)
    clear_settings_cache()
    reset_db_caches()
    yield
    clear_settings_cache()
    reset_db_caches()


@contextmanager
def temp_postgres_database():
    """A throw-away PostgreSQL database (created, yielded as a URL string, dropped)."""
    base = _base_pg_url()
    admin = make_engine(base, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect():
            pass
    except OperationalError:
        admin.dispose()
        pytest.skip(f"PostgreSQL not reachable at {base} (run: make up)")
    name = f"sie_test_{uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f"CREATE DATABASE {name}"))
    url = make_url(base).set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
        admin.dispose()


@pytest.fixture
def sqlite_engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    yield engine
    engine.dispose()


@pytest.fixture
def pg_engine():
    """The dev PostgreSQL itself, for simple connectivity tests; skipped when unreachable."""
    engine = make_engine(_base_pg_url())
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip(f"PostgreSQL not reachable at {_base_pg_url()} (run: make up)")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def _pg_migrated_url():
    """One migrated PostgreSQL database for the whole test session."""
    with temp_postgres_database() as url:
        engine = make_engine(url)
        migrate.upgrade(engine)
        engine.dispose()
        yield url


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.integration)])
def engine(request):
    """A freshly migrated, empty database. Behaviour tests run on SQLite and PostgreSQL."""
    if request.param == "sqlite":
        eng = make_engine("sqlite+pysqlite:///:memory:")
        migrate.upgrade(eng)
    else:
        url = request.getfixturevalue("_pg_migrated_url")
        eng = make_engine(url)
        with eng.begin() as conn:
            conn.execute(text(f"TRUNCATE {ALL_TABLES} RESTART IDENTITY CASCADE"))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    """A session on the migrated database; whatever a test leaves uncommitted is rolled back."""
    s = make_session_factory(engine)()
    yield s
    s.rollback()
    s.close()
