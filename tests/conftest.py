import os
import socket
from contextlib import contextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from tools import pgtemp

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
    try:
        with pgtemp.temp_database(_base_pg_url()) as url:
            yield url
    except pgtemp.PostgresUnavailable as exc:
        pytest.skip(str(exc))


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


class NetworkBlocked(RuntimeError):
    """Raised when a test (or code under test) tries to open a non-local network connection."""


def _is_local(host: str) -> bool:
    return host in ("localhost", "::1") or host.startswith("127.")


@pytest.fixture(scope="session", autouse=True)
def _block_external_network():
    """Tests must never reach Telegram or any third party (TASKS.md rule 5, requirement A-08).

    Only loopback connections are allowed (the local PostgreSQL). psycopg's libpq talks to the
    database outside Python sockets, which is fine because that target is the local server.
    """
    real_connect, real_connect_ex = socket.socket.connect, socket.socket.connect_ex

    def check(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(str(address[0])):
            raise NetworkBlocked(f"tests may not connect to {address[0]}:{address[1]}")

    def guarded_connect(self, address):
        check(self, address)
        return real_connect(self, address)

    def guarded_connect_ex(self, address):
        check(self, address)
        return real_connect_ex(self, address)

    socket.socket.connect, socket.socket.connect_ex = guarded_connect, guarded_connect_ex
    yield
    socket.socket.connect, socket.socket.connect_ex = real_connect, real_connect_ex
