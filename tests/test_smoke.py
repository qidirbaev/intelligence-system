import importlib

import pytest
from alembic.script import ScriptDirectory
from typer.testing import CliRunner

import sie
from sie.cli import app
from sie.storage import migrate

SUBPACKAGES = [
    "compliance",
    "policy",
    "language",
    "ingest",
    "adapters",
    "l0",
    "l1",
    "brain",
    "comments",
    "storage",
    "queue",
    "api",
    "dashboard",
    "eval",
]


def test_version_string():
    assert sie.__version__ == "0.1.0"


def test_cli_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == sie.__version__


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_importable(name):
    module = importlib.import_module(f"sie.{name}")
    assert module.__doc__, f"sie.{name} needs a docstring stating its responsibility"


def test_cli_db_ping_ok(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    result = CliRunner().invoke(app, ["db-ping"])
    assert result.exit_code == 0
    assert "ok" in result.output


def test_cli_db_ping_failure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:////nonexistent_dir_for_sie/x.db")
    result = CliRunner().invoke(app, ["db-ping"])
    assert result.exit_code == 1


def test_cli_migration_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'cli.db'}")
    runner = CliRunner()
    assert runner.invoke(app, ["db-current"]).stdout.strip() == "none"
    head = ScriptDirectory.from_config(migrate.alembic_config()).get_current_head()
    assert head in runner.invoke(app, ["db-upgrade"]).stdout
    assert runner.invoke(app, ["db-current"]).stdout.strip() == head
    assert "None" in runner.invoke(app, ["db-downgrade", "base"]).stdout
