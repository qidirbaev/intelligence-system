"""Alembic environment. Works from the CLI, from `sie db-upgrade`, and programmatically
(tests pass an open connection through `config.attributes['connection']`)."""

from alembic import context

import sie.storage.models  # noqa: F401  (registers every table on Base.metadata)
from sie.config import get_settings
from sie.storage.base import Base
from sie.storage.db import make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied = config.attributes.get("connection")
    if supplied is not None:
        _configure(supplied)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = make_engine(_url())
    try:
        with engine.connect() as connection:
            _configure(connection)
            with context.begin_transaction():
                context.run_migrations()
            connection.commit()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
