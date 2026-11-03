"""Behaviour of the registry, compliance, policy and audit tables (migrated schema).

Runs on SQLite and, when reachable, on PostgreSQL (see the `engine` fixture).
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError

from sie.config import clear_settings_cache
from sie.storage import repos
from sie.storage.enums import AccessBasisType
from sie.storage.models import AccessBasis, AgentState, AuditLog, PolicyVersion, Source


def make_source(session, external_id="chan1", **kwargs):
    return repos.add_source(session, "telegram", external_id, **kwargs)


# ---------- persons and sources ----------


def test_source_defaults_and_agent_state(session):
    person = repos.add_person(session, "Test Figure", "blogger")
    source = make_source(session, handle="@chan1", person_id=person.person_id)
    session.commit()
    session.refresh(source)
    assert source.status == "active" and source.priority == 0 and source.tags == []
    assert source.tenant_id == "default"
    assert source.created_at.tzinfo is not None
    state = session.get(AgentState, source.source_id)
    assert state.interval_s == 300 and state.failures == 0 and state.cursor == {}
    assert state.memory == {} and state.next_check_at is None


def test_tags_roundtrip_as_json_list(session):
    source = make_source(session, tags=["public_figure", "priority_figure"])
    session.commit()
    session.expire_all()
    assert session.get(Source, source.source_id).tags == ["public_figure", "priority_figure"]


def test_source_unique_per_tenant_platform_external_id(session):
    make_source(session, "dup")
    session.commit()
    with pytest.raises(IntegrityError):
        make_source(session, "dup")


def test_same_external_id_on_another_platform_is_fine(session):
    make_source(session, "same")
    repos.add_source(session, "threads", "same")
    session.commit()


def test_invalid_source_status_rejected(session):
    source = make_source(session)
    source.status = "weird"
    with pytest.raises(IntegrityError):
        session.flush()


def test_deleting_person_keeps_source(session):
    person = repos.add_person(session, "P")
    source = make_source(session, person_id=person.person_id)
    session.commit()
    session.delete(person)
    session.commit()
    session.refresh(source)
    assert source.person_id is None


def test_get_source_finds_by_platform_and_external_id(session):
    source = make_source(session, "findme")
    session.commit()
    assert repos.get_source(session, "telegram", "findme").source_id == source.source_id
    assert repos.get_source(session, "telegram", "missing") is None


# ---------- access bases (compliance gate) ----------


def test_access_basis_defaults_deny_comments(session):
    source = make_source(session)
    basis = repos.add_access_basis(
        session, source.source_id, AccessBasisType.OWNER_CONSENT, document_ref="consent-001"
    )
    session.commit()
    session.refresh(basis)
    assert basis.comments_allowed is False
    assert basis.revoked_at is None and basis.valid_to is None
    assert basis.valid_from.tzinfo is not None


def test_access_basis_invalid_type_rejected(session):
    source = make_source(session)
    with pytest.raises(IntegrityError):
        repos.add_access_basis(session, source.source_id, "scraping_is_fine", document_ref="x")


def test_document_ref_required_except_for_own_channel(session):
    source = make_source(session)
    repos.add_access_basis(session, source.source_id, AccessBasisType.OWN_CHANNEL)  # ok
    with pytest.raises(IntegrityError):
        repos.add_access_basis(session, source.source_id, AccessBasisType.TELEGRAM_PERMISSION)


def test_validity_window_must_be_ordered(session):
    source = make_source(session)
    now = datetime.now(UTC)
    with pytest.raises(IntegrityError):
        repos.add_access_basis(
            session,
            source.source_id,
            AccessBasisType.OWN_CHANNEL,
            valid_from=now,
            valid_to=now - timedelta(days=1),
        )


def test_basis_for_unknown_source_rejected(session):
    with pytest.raises(IntegrityError):
        repos.add_access_basis(session, 999999, AccessBasisType.OWN_CHANNEL)


def test_source_with_basis_cannot_be_deleted(session):
    source = make_source(session)
    repos.add_access_basis(session, source.source_id, AccessBasisType.OWN_CHANNEL)
    session.commit()
    session.delete(source)
    with pytest.raises(IntegrityError):
        session.flush()


def test_naive_datetimes_are_rejected(session):
    source = make_source(session)
    with pytest.raises(StatementError, match="naive datetime"):
        repos.add_access_basis(
            session, source.source_id, AccessBasisType.OWN_CHANNEL, valid_from=datetime(2026, 1, 1)
        )


def test_revoke_sets_time_and_audits_once(session):
    source = make_source(session)
    basis = repos.add_access_basis(session, source.source_id, AccessBasisType.OWN_CHANNEL)
    repos.revoke_access_basis(session, basis.basis_id, actor="operator:ann")
    repos.revoke_access_basis(session, basis.basis_id, actor="operator:ann")  # idempotent
    session.commit()
    session.refresh(basis)
    assert basis.revoked_at is not None
    actions = session.scalars(select(AuditLog.action).order_by(AuditLog.audit_id)).all()
    assert actions == ["basis.created", "basis.revoked"]
    revoked = session.scalars(select(AuditLog).where(AuditLog.action == "basis.revoked")).one()
    assert revoked.actor == "operator:ann" and revoked.object == f"access_basis:{basis.basis_id}"


def test_revoke_unknown_basis_raises(session):
    with pytest.raises(LookupError):
        repos.revoke_access_basis(session, 424242)


def test_list_access_bases_in_order(session):
    source = make_source(session)
    a = repos.add_access_basis(session, source.source_id, AccessBasisType.OWN_CHANNEL)
    b = repos.add_access_basis(
        session, source.source_id, AccessBasisType.OWNER_CONSENT, document_ref="c"
    )
    assert [x.basis_id for x in repos.list_access_bases(session, source.source_id)] == [
        a.basis_id,
        b.basis_id,
    ]


# ---------- agent state ----------


def test_deleting_source_removes_agent_state(session):
    source = make_source(session)
    session.commit()
    source_id = source.source_id
    session.delete(source)
    session.commit()
    assert session.get(AgentState, source_id) is None


@pytest.mark.parametrize("field,value", [("interval_s", 0), ("failures", -1)])
def test_agent_state_checks(session, field, value):
    source = make_source(session)
    session.flush()
    setattr(source.agent_state, field, value)
    with pytest.raises(IntegrityError):
        session.flush()


def test_agent_state_cursor_and_memory_roundtrip(session):
    source = make_source(session)
    source.agent_state.cursor = {"last_msg_id": 48213}
    source.agent_state.memory = {"m1": {"pending": [1, 2]}}
    session.commit()
    session.expire_all()
    state = session.get(AgentState, source.source_id)
    assert state.cursor == {"last_msg_id": 48213}
    assert state.memory["m1"]["pending"] == [1, 2]


# ---------- policy versions ----------


def test_policy_version_lifecycle_rules(session):
    now = datetime.now(UTC)
    session.add(PolicyVersion(version=1, bundle={"policy_version": 1}))  # draft is fine
    session.add(PolicyVersion(version=2, status="validated", bundle={}))
    session.flush()

    session.add(PolicyVersion(version=3, status="approved", bundle={}))  # no approver
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add(
        PolicyVersion(version=4, status="published", approved_by="ann", bundle={})
    )  # no effective_from
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add(PolicyVersion(version=5, status="nonsense", bundle={}))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add(
        PolicyVersion(
            version=6,
            status="published",
            approved_by="ann",
            effective_from=now,
            bundle={"post_rules": [{"id": "default", "decide": "DROP"}]},
        )
    )
    session.commit()
    session.expire_all()
    published = session.get(PolicyVersion, 6)
    assert published.bundle["post_rules"][0]["decide"] == "DROP"
    assert published.effective_from.tzinfo is not None


# ---------- audit log and tenants ----------


def test_audit_entry_roundtrip(session):
    repos.append_audit(session, "system", "x.happened", "thing:1", {"n": 1, "ok": True})
    session.commit()
    entry = session.scalars(select(AuditLog)).one()
    assert entry.detail == {"n": 1, "ok": True}
    assert entry.ts.tzinfo is not None and entry.tenant_id == "default"


def test_tenant_default_follows_settings(session, monkeypatch):
    monkeypatch.setenv("SIE_TENANT_ID", "acme")
    clear_settings_cache()
    person = repos.add_person(session, "Tenant Test")
    source = make_source(session, "t1")
    session.commit()
    assert person.tenant_id == "acme" and source.tenant_id == "acme"
    assert repos.get_source(session, "telegram", "t1").source_id == source.source_id
    monkeypatch.setenv("SIE_TENANT_ID", "other")
    clear_settings_cache()
    assert repos.get_source(session, "telegram", "t1") is None  # not visible to another tenant


def test_models_are_registered(session):
    assert session.scalar(select(AccessBasis).limit(1)) is None
