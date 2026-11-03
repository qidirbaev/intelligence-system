import pytest
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column

from sie.storage.base import NAMING_CONVENTION, Base
from sie.storage.db import make_engine, make_session_factory, ping, session_scope


def test_commit_persists_and_rollback_discards(sqlite_engine):
    factory = make_session_factory(sqlite_engine)
    with session_scope(factory) as s:
        s.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)"))
        s.execute(text("INSERT INTO t (v) VALUES ('kept')"))

    with pytest.raises(RuntimeError):
        with session_scope(factory) as s:
            s.execute(text("INSERT INTO t (v) VALUES ('discarded')"))
            raise RuntimeError("fail inside the scope")

    with session_scope(factory) as s:
        rows = s.execute(text("SELECT v FROM t")).scalars().all()
    assert rows == ["kept"]


def test_sqlite_enforces_foreign_keys(sqlite_engine):
    with sqlite_engine.connect() as c:
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_ping(sqlite_engine):
    assert ping(sqlite_engine) is True
    broken = make_engine("sqlite+pysqlite:////nonexistent_dir_for_sie/x.db")
    assert ping(broken) is False


def test_naming_convention_applies_to_models(sqlite_engine):
    class Thing(Base):
        __tablename__ = "thing_naming_test"
        id: Mapped[int] = mapped_column(primary_key=True)
        code: Mapped[str] = mapped_column(unique=True)

    try:
        Base.metadata.create_all(sqlite_engine)
        names = {c.name for c in Thing.__table__.constraints}
        assert "pk_thing_naming_test" in names
        assert "uq_thing_naming_test_code" in names
        assert set(NAMING_CONVENTION) == {"ix", "uq", "ck", "fk", "pk"}
    finally:
        Base.metadata.remove(Thing.__table__)


@pytest.mark.integration
def test_postgres_connects_and_has_pgvector(pg_engine):
    assert ping(pg_engine) is True
    with pg_engine.connect() as c:
        available = c.execute(
            text("SELECT count(*) FROM pg_available_extensions WHERE name = 'vector'")
        ).scalar()
    assert available == 1


@pytest.mark.integration
def test_postgres_rollback_is_real(pg_engine):
    factory = make_session_factory(pg_engine)
    with session_scope(factory) as s:
        s.execute(text("CREATE TEMP TABLE tmp_t (v int)"))
        s.execute(text("INSERT INTO tmp_t VALUES (1)"))
        assert s.execute(text("SELECT count(*) FROM tmp_t")).scalar() == 1
    # the temp table vanished with the connection; a failing scope must not leak writes
    with pytest.raises(RuntimeError):
        with session_scope(factory) as s:
            s.execute(text("CREATE TABLE IF NOT EXISTS sie_t02_probe (v int)"))
            s.execute(text("INSERT INTO sie_t02_probe VALUES (1)"))
            raise RuntimeError("abort")
    with session_scope(factory) as s:
        exists = s.execute(text("SELECT to_regclass('public.sie_t02_probe')")).scalar()
    assert exists is None  # DDL is transactional in Postgres, so it rolled back too
