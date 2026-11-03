"""Programmatic Alembic helpers (used by the CLI and by tests)."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def upgrade(engine: Engine, revision: str = "head") -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)


def downgrade(engine: Engine, revision: str = "base") -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
