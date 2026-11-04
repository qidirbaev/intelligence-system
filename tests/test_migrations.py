import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

import sie.storage.models  # noqa: F401
from sie.storage import migrate
from sie.storage.base import Base
from sie.storage.db import make_engine
from tests.conftest import temp_postgres_database

FIRST_MIGRATION_TABLES = {
    "access_basis",
    "agent_state",
    "audit_log",
    "persons",
    "policy_versions",
    "sources",
}
EXPECTED_TABLES = FIRST_MIGRATION_TABLES | {
    "audit_samples",
    "budget_counters",
    "content_items",
    "dead_letters",
    "decisions",
    "operator_tasks",
    "rechecks",
}


def user_tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_single_head_is_0002():
    script = ScriptDirectory.from_config(migrate.alembic_config())
    assert script.get_heads() == ["0002"]


def test_sqlite_round_trip(sqlite_engine):
    assert migrate.current_revision(sqlite_engine) is None
    migrate.upgrade(sqlite_engine)
    assert migrate.current_revision(sqlite_engine) == "0002"
    assert user_tables(sqlite_engine) == EXPECTED_TABLES
    migrate.downgrade(sqlite_engine, "base")
    assert user_tables(sqlite_engine) == set()
    migrate.upgrade(sqlite_engine)
    assert user_tables(sqlite_engine) == EXPECTED_TABLES


def models_vs_database(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)


def test_models_match_migration_on_sqlite(sqlite_engine):
    migrate.upgrade(sqlite_engine)
    assert models_vs_database(sqlite_engine) == []


@pytest.mark.integration
def test_models_match_migration_on_postgres():
    with temp_postgres_database() as url:
        engine = make_engine(url)
        migrate.upgrade(engine)
        assert models_vs_database(engine) == []
        engine.dispose()


@pytest.mark.integration
def test_postgres_round_trip_removes_everything():
    with temp_postgres_database() as url:
        engine = make_engine(url)
        migrate.upgrade(engine)
        assert user_tables(engine) == EXPECTED_TABLES
        migrate.downgrade(engine, "base")
        assert user_tables(engine) == set()
        with engine.connect() as c:
            leftover = c.execute(
                text("SELECT count(*) FROM pg_proc WHERE proname = 'audit_log_immutable'")
            ).scalar()
        assert leftover == 0
        migrate.upgrade(engine)  # and up again
        assert user_tables(engine) == EXPECTED_TABLES
        engine.dispose()


@pytest.mark.integration
def test_postgres_uses_jsonb_and_named_constraints():
    with temp_postgres_database() as url:
        engine = make_engine(url)
        migrate.upgrade(engine)
        with engine.connect() as c:
            types = dict(
                c.execute(
                    text(
                        "SELECT table_name || '.' || column_name, data_type "
                        "FROM information_schema.columns WHERE data_type IN ('jsonb', 'json')"
                    )
                ).all()
            )
            names = set(
                c.execute(
                    text(
                        "SELECT conname FROM pg_constraint "
                        "WHERE conrelid IN ('sources'::regclass, 'access_basis'::regclass)"
                    )
                ).scalars()
            )
        assert types["sources.tags"] == "jsonb"
        assert types["policy_versions.bundle"] == "jsonb"
        assert types["agent_state.cursor"] == "jsonb"
        assert {
            "pk_sources",
            "fk_sources_person_id_persons",
            "uq_sources_tenant_id",
            "ck_sources_status_valid",
            "ck_access_basis_document_ref_required",
            "fk_access_basis_source_id_sources",
        } <= names
        engine.dispose()


@pytest.mark.integration
def test_audit_log_is_append_only_on_postgres():
    with temp_postgres_database() as url:
        engine = make_engine(url)
        migrate.upgrade(engine)
        with engine.begin() as c:
            c.execute(text("INSERT INTO audit_log (actor, action, object) VALUES ('a','b','c')"))
        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as c:
                c.execute(text("UPDATE audit_log SET actor = 'tampered'"))
        with pytest.raises(DBAPIError, match="append-only"):
            with engine.begin() as c:
                c.execute(text("DELETE FROM audit_log"))
        with engine.connect() as c:
            assert c.execute(text("SELECT actor FROM audit_log")).scalar() == "a"
        engine.dispose()


def test_drift_detector_is_not_vacuous(sqlite_engine):
    """Comparing the migrated database with *empty* metadata must report differences."""
    from sqlalchemy import MetaData

    migrate.upgrade(sqlite_engine)
    with sqlite_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        diff = compare_metadata(context, MetaData())
    removed = {entry[1].name for entry in diff if entry[0] == "remove_table"}
    assert EXPECTED_TABLES <= removed


def test_downgrade_one_step_keeps_the_first_migration(sqlite_engine):
    migrate.upgrade(sqlite_engine)
    migrate.downgrade(sqlite_engine, "0001")
    assert migrate.current_revision(sqlite_engine) == "0001"
    assert user_tables(sqlite_engine) == FIRST_MIGRATION_TABLES
    migrate.upgrade(sqlite_engine)
    assert user_tables(sqlite_engine) == EXPECTED_TABLES


@pytest.mark.integration
def test_postgres_step_down_and_up_keeps_data_of_the_first_migration():
    from sie.storage import repos
    from sie.storage.db import make_session_factory, session_scope

    with temp_postgres_database() as url:
        engine = make_engine(url)
        migrate.upgrade(engine)
        factory = make_session_factory(engine)
        with session_scope(factory) as s:
            repos.add_source(s, "telegram", "keep_me")
        migrate.downgrade(engine, "0001")
        assert user_tables(engine) == FIRST_MIGRATION_TABLES
        migrate.upgrade(engine)
        with session_scope(factory) as s:
            assert repos.get_source(s, "telegram", "keep_me") is not None
        engine.dispose()


@pytest.mark.integration
def test_postgres_new_json_columns_are_jsonb():
    with temp_postgres_database() as url:
        engine = make_engine(url)
        migrate.upgrade(engine)
        with engine.connect() as c:
            types = dict(
                c.execute(
                    text(
                        "SELECT table_name || '.' || column_name, data_type "
                        "FROM information_schema.columns WHERE data_type IN ('jsonb', 'json')"
                    )
                ).all()
            )
        for column in (
            "content_items.metrics",
            "decisions.reasons",
            "dead_letters.envelope",
            "operator_tasks.detail",
        ):
            assert types[column] == "jsonb", column
        engine.dispose()
