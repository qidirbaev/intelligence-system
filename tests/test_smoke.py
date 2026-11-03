import importlib

import pytest
from typer.testing import CliRunner

import sie
from sie.cli import app

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
