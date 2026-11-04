"""Throw-away PostgreSQL databases for tests, the demo and verification.

CLI (used by tools/verify.py):  python -m tools.pgtemp check|create|drop <name>
Needs a role that may CREATE DATABASE (the docker-compose role is a superuser).
"""

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url

from sie.config import DEV_DATABASE_URL
from sie.storage.db import make_engine


class PostgresUnavailable(RuntimeError):
    """PostgreSQL is not reachable with the given URL."""


def base_url() -> str:
    return (
        os.environ.get("SIE_TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or DEV_DATABASE_URL
    )


def _hidden(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def check(url: str | None = None) -> str:
    """Return the server version string, or raise PostgresUnavailable with a helpful message."""
    url = url or base_url()
    engine = make_engine(url)
    try:
        with engine.connect() as connection:
            return str(connection.execute(text("SELECT version()")).scalar())
    except Exception as exc:
        raise PostgresUnavailable(
            f"cannot connect to PostgreSQL at {_hidden(url)} ({type(exc).__name__}). "
            "Start it with `docker compose up -d db`, or pass --database-url."
        ) from exc
    finally:
        engine.dispose()


def create(url: str | None = None) -> tuple[str, str]:
    """Create an empty database; returns (name, url_to_it)."""
    url = url or base_url()
    check(url)
    name = f"sie_tmp_{uuid4().hex[:12]}"
    admin = make_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {name}"))
    finally:
        admin.dispose()
    new_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    return name, new_url


def drop(name: str, url: str | None = None) -> None:
    if not name.startswith("sie_tmp_") and not name.startswith("sie_test_"):
        raise ValueError("refusing to drop a database that is not a throw-away one")
    admin = make_engine(url or base_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))
    finally:
        admin.dispose()


@contextmanager
def temp_database(url: str | None = None) -> Iterator[str]:
    name, new_url = create(url)
    try:
        yield new_url
    finally:
        drop(name, url)


def main(argv: list[str]) -> int:
    command = argv[0] if argv else ""
    try:
        if command == "check":
            print(check())
        elif command == "create":
            name, new_url = create()
            print(f"{name}\t{new_url}")
        elif command == "drop" and len(argv) == 2:
            drop(argv[1])
        else:
            print(__doc__)
            return 2
    except PostgresUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
