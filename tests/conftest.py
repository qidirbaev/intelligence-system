import os

import pytest
from sqlalchemy.exc import OperationalError

from sie.config import DEV_DATABASE_URL, clear_settings_cache
from sie.storage.db import make_engine, reset_db_caches

_ENV_PREFIXES = ("SIE_",)
_ENV_NAMES = ("DATABASE_URL", "TELEGRAM_API_ID", "TELEGRAM_API_HASH")
_KEEP = {"SIE_TEST_DATABASE_URL"}  # test-infrastructure setting, not application config


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


@pytest.fixture
def sqlite_engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    yield engine
    engine.dispose()


@pytest.fixture
def pg_engine():
    """PostgreSQL for @pytest.mark.integration tests; skipped when it is not reachable."""
    url = os.environ.get("SIE_TEST_DATABASE_URL", DEV_DATABASE_URL)
    engine = make_engine(url)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip(f"PostgreSQL not reachable at {url} (run: make up)")
    yield engine
    engine.dispose()
