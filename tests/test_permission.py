"""The compliance gate: permission engine (requirements CG-1, CG-2, CG-3, V-08, AC-1)."""

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from sie.compliance import permission as perm
from sie.compliance.permission import AccessDenied, Action, evaluate_access
from sie.config import clear_settings_cache
from sie.storage import repos
from sie.storage.db import make_session_factory
from sie.storage.enums import AccessBasisType, SourceStatus
from sie.storage.models import AuditLog

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
READS = [Action.READ_POSTS, Action.READ_REACTIONS, Action.READ_COMMENTS]
NOT_GRANTABLE = [Action.DOWNLOAD_MEDIA, Action.PROFILE_COMMENTERS, Action.INFER_SENSITIVE_TRAITS]


@dataclass
class B:
    basis_id: int = 1
    type: str = "own_channel"
    tenant_id: str = "default"
    comments_allowed: bool = False
    valid_from: datetime = NOW - 24 * HOUR
    valid_to: datetime | None = None
    revoked_at: datetime | None = None


@dataclass
class S:
    source_id: int = 1
    tenant_id: str = "default"
    status: str = "active"


ACTIVE_SOURCE = S()


def decide(bases, action=Action.READ_POSTS, source=ACTIVE_SOURCE, now=NOW, tenant="default"):
    return evaluate_access(source, bases, action, source_id=1, now=now, tenant_id=tenant)


# ====================== pure decision function ======================


def test_no_basis_means_no_reading_of_any_kind():
    for action in READS:
        decision = decide([], action)
        assert not decision.allowed and decision.code == perm.NO_ACCESS_BASIS


def test_valid_basis_allows_posts_and_reactions_but_not_comments():
    basis = [B()]
    assert decide(basis, Action.READ_POSTS).allowed
    assert decide(basis, Action.READ_REACTIONS).allowed
    comments = decide(basis, Action.READ_COMMENTS)
    assert not comments.allowed and comments.code == perm.COMMENTS_NOT_ALLOWED


def test_owner_consent_alone_never_grants_comments():  # CG-3
    consent = B(type="owner_consent", comments_allowed=False)
    assert decide([consent], Action.READ_POSTS).allowed
    assert not decide([consent], Action.READ_COMMENTS).allowed


def test_comments_need_explicit_permission_on_a_valid_basis():
    assert decide([B(comments_allowed=True)], Action.READ_COMMENTS).allowed
    # permission on a revoked basis does not count
    revoked = B(comments_allowed=True, revoked_at=NOW - HOUR)
    assert not decide([revoked], Action.READ_COMMENTS).allowed


def test_revoked_basis_is_dead_whenever_it_was_revoked():
    for revoked_at in (NOW - HOUR, NOW, NOW + HOUR):  # even a "future" revocation counts
        assert not decide([B(revoked_at=revoked_at)]).allowed


def test_validity_window_boundaries():
    assert decide([B(valid_from=NOW)]).allowed  # in force exactly now
    assert not decide([B(valid_from=NOW + timedelta(seconds=1))]).allowed
    assert not decide([B(valid_to=NOW)]).allowed  # expires exactly now
    assert decide([B(valid_to=NOW + timedelta(seconds=1))]).allowed
    decision = decide([B(valid_to=NOW - HOUR)])
    assert decision.code == perm.NO_VALID_ACCESS_BASIS and "expired" in decision.reasons[0]


def test_any_one_valid_basis_is_enough_and_is_reported():
    bases = [
        B(basis_id=1, revoked_at=NOW - HOUR),
        B(basis_id=2, valid_to=NOW - HOUR),
        B(basis_id=3, type="owner_consent"),
    ]
    decision = decide(bases)
    assert decision.allowed and decision.basis_id == 3 and decision.basis_type == "owner_consent"


def test_comments_can_come_from_a_different_basis_than_posts():
    bases = [B(basis_id=1), B(basis_id=2, type="owner_consent", comments_allowed=True)]
    assert decide(bases, Action.READ_COMMENTS).basis_id == 2
    assert decide(bases, Action.READ_POSTS).basis_id == 1


def test_denial_explains_every_basis():
    bases = [B(basis_id=4, revoked_at=NOW - HOUR), B(basis_id=5, valid_from=NOW + HOUR)]
    decision = decide(bases)
    assert len(decision.reasons) == 2
    assert "basis 4" in decision.reasons[0] and "revoked" in decision.reasons[0]
    assert "basis 5" in decision.reasons[1] and "not yet valid" in decision.reasons[1]


@pytest.mark.parametrize(
    "status,code", [("paused", perm.SOURCE_PAUSED), ("disabled", perm.SOURCE_DISABLED)]
)
def test_paused_or_disabled_source_is_denied_despite_a_valid_basis(status, code):
    decision = decide([B()], source=S(status=status))
    assert not decision.allowed and decision.code == code


def test_unknown_source_and_other_tenant_are_denied():
    assert decide([B()], source=None).code == perm.UNKNOWN_SOURCE
    assert decide([B()], source=S(tenant_id="other")).code == perm.TENANT_MISMATCH


def test_a_basis_of_another_tenant_does_not_count():
    assert decide([B(tenant_id="other")]).code == perm.NO_ACCESS_BASIS


@pytest.mark.parametrize("action", NOT_GRANTABLE + ["scrape_everything", "", "READ_POSTS"])
def test_actions_a_basis_cannot_grant_are_always_denied(action):
    decision = decide([B(comments_allowed=True)], action)
    assert not decision.allowed and decision.code == perm.ACTION_NOT_SUPPORTED


def test_naive_time_is_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        decide([B()], now=datetime(2026, 11, 10, 12, 0))


# ====================== properties over many random situations ======================

TYPES = [t.value for t in AccessBasisType]


@st.composite
def bases_strategy(draw):
    count = draw(st.integers(0, 4))
    items = []
    for i in range(count):
        start = NOW + draw(st.integers(-72, 72)) * HOUR
        end = None if draw(st.booleans()) else start + draw(st.integers(1, 96)) * HOUR
        revoked = NOW + draw(st.integers(-72, 72)) * HOUR if draw(st.booleans()) else None
        items.append(
            B(
                basis_id=i + 1,
                type=draw(st.sampled_from(TYPES)),
                tenant_id=draw(st.sampled_from(["default", "default", "default", "other"])),
                comments_allowed=draw(st.booleans()),
                valid_from=start,
                valid_to=end,
                revoked_at=revoked,
            )
        )
    return items


def oracle(bases, action, source_status="active"):
    """Independent restatement of the rule, written differently on purpose."""
    if source_status != "active" or action not in READS:
        return False
    return any(
        b.tenant_id == "default"
        and b.revoked_at is None
        and b.valid_from <= NOW
        and (b.valid_to is None or NOW < b.valid_to)
        and (action is not Action.READ_COMMENTS or b.comments_allowed)
        for b in bases
    )


@settings(max_examples=400, deadline=None)
@given(bases=bases_strategy(), action=st.sampled_from(list(Action)))
def test_property_decision_matches_the_rule(bases, action):
    assert decide(bases, action).allowed == oracle(bases, action)


@settings(max_examples=300, deadline=None)
@given(bases=bases_strategy())
def test_property_comments_are_never_easier_than_posts(bases):
    if decide(bases, Action.READ_COMMENTS).allowed:
        assert decide(bases, Action.READ_POSTS).allowed


@settings(max_examples=300, deadline=None)
@given(bases=bases_strategy(), action=st.sampled_from(READS))
def test_property_revoking_everything_always_denies(bases, action):
    revoked = [replace(b, revoked_at=NOW - HOUR) for b in bases]
    assert not decide(revoked, action).allowed


@settings(max_examples=300, deadline=None)
@given(
    bases=bases_strategy(),
    action=st.sampled_from(READS),
    status=st.sampled_from(["paused", "disabled"]),
)
def test_property_inactive_source_is_never_readable(bases, action, status):
    assert not decide(bases, action, source=S(status=status)).allowed


@settings(max_examples=300, deadline=None)
@given(bases=bases_strategy(), action=st.sampled_from(NOT_GRANTABLE))
def test_property_ungrantable_actions_are_never_allowed(bases, action):
    assert not decide(bases, action).allowed


@settings(max_examples=200, deadline=None)
@given(action=st.sampled_from(list(Action)))
def test_property_a_source_without_any_basis_is_never_readable(action):  # AC-1
    assert not decide([], action).allowed


# ====================== with the database (SQLite and PostgreSQL) ======================


def new_source(session, external_id="chan"):
    return repos.add_source(session, "telegram", external_id)


def basis(session, source, type_=AccessBasisType.OWN_CHANNEL, **kwargs):
    kwargs.setdefault("valid_from", NOW - 24 * HOUR)
    if type_ != AccessBasisType.OWN_CHANNEL:
        kwargs.setdefault("document_ref", "doc-1")
    return repos.add_access_basis(session, source.source_id, type_, **kwargs)


def denials(session):
    return list(session.scalars(select(AuditLog).where(AuditLog.action == "access.denied")))


def test_source_without_basis_is_denied_and_the_denial_is_audited(session):
    source = new_source(session)
    decision = perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW)
    session.commit()
    assert not decision.allowed and decision.code == perm.NO_ACCESS_BASIS
    [entry] = denials(session)
    assert entry.object == f"source:{source.source_id}" and entry.ts == NOW
    assert entry.detail["action"] == "read_posts" and entry.detail["code"] == perm.NO_ACCESS_BASIS


def test_valid_basis_is_allowed_and_nothing_is_logged(session):
    source = new_source(session)
    basis(session, source)
    decision = perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW)
    assert decision.allowed and decision.basis_type == "own_channel"
    assert denials(session) == []


def test_revoking_a_basis_takes_effect_immediately(session):
    source = new_source(session)
    created = basis(session, source)
    assert perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW).allowed
    repos.revoke_access_basis(session, created.basis_id, at=NOW)
    after = perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW)
    assert not after.allowed and "revoked" in after.reasons[0]


def test_expiry_and_future_start_are_enforced_from_the_database(session):
    source = new_source(session)
    basis(session, source, valid_to=NOW)  # expires exactly now
    assert not perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW).allowed
    assert perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW - HOUR).allowed
    later = new_source(session, "later")
    basis(session, later, valid_from=NOW + HOUR)
    assert not perm.check_access(session, later.source_id, Action.READ_POSTS, now=NOW).allowed


def test_comments_denied_unless_the_basis_allows_them(session):
    source = new_source(session)
    basis(session, source, AccessBasisType.OWNER_CONSENT)  # comments_allowed defaults to False
    decision = perm.check_access(session, source.source_id, Action.READ_COMMENTS, now=NOW)
    assert not decision.allowed and decision.code == perm.COMMENTS_NOT_ALLOWED
    basis(session, source, AccessBasisType.TELEGRAM_PERMISSION, comments_allowed=True)
    assert perm.check_access(session, source.source_id, Action.READ_COMMENTS, now=NOW).allowed


def test_paused_source_is_denied_until_reactivated(session):
    source = new_source(session)
    basis(session, source)
    source.status = SourceStatus.PAUSED.value
    session.flush()
    assert (
        perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW).code
        == perm.SOURCE_PAUSED
    )
    source.status = SourceStatus.ACTIVE.value
    session.flush()
    assert perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW).allowed


def test_unknown_source_is_denied_and_logged(session):
    decision = perm.check_access(session, 987654, Action.READ_POSTS, now=NOW)
    assert decision.code == perm.UNKNOWN_SOURCE
    assert denials(session)[0].object == "source:987654"


@pytest.mark.parametrize("action", NOT_GRANTABLE + ["scrape_everything"])
def test_unsupported_actions_are_denied_even_with_a_perfect_basis(session, action):
    source = new_source(session)
    basis(session, source, comments_allowed=True)
    decision = perm.check_access(session, source.source_id, action, now=NOW)
    assert not decision.allowed and decision.code == perm.ACTION_NOT_SUPPORTED


def test_source_of_another_tenant_is_denied(session, monkeypatch):
    monkeypatch.setenv("SIE_TENANT_ID", "acme")
    clear_settings_cache()
    source = new_source(session, "acme_chan")
    basis(session, source)
    assert perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW).allowed
    monkeypatch.setenv("SIE_TENANT_ID", "someone_else")
    clear_settings_cache()
    decision = perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW)
    assert decision.code == perm.TENANT_MISMATCH


# ---------- denial logging ----------


def test_repeated_denials_are_audited_once_per_window_but_always_logged(session, caplog):
    source = new_source(session)
    sid = source.source_id
    with caplog.at_level(logging.WARNING, logger="sie.compliance"):
        perm.check_access(session, sid, Action.READ_POSTS, now=NOW)
        perm.check_access(session, sid, Action.READ_POSTS, now=NOW + 10 * timedelta(minutes=1))
        assert len(denials(session)) == 1  # same source, action and reason within the hour
        perm.check_access(session, sid, Action.READ_COMMENTS, now=NOW + timedelta(minutes=11))
        assert len(denials(session)) == 2  # a different action is a different denial
        perm.check_access(session, sid, Action.READ_POSTS, now=NOW + timedelta(minutes=61))
        assert len(denials(session)) == 3  # the window passed
    assert len([r for r in caplog.records if r.getMessage() == "access denied"]) == 4
    assert {r.code for r in caplog.records if hasattr(r, "code")} == {perm.NO_ACCESS_BASIS}


def test_a_new_reason_for_the_same_action_is_audited_again(session):
    source = new_source(session)
    perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW)  # no basis
    created = basis(session, source)
    repos.revoke_access_basis(session, created.basis_id, at=NOW)
    perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW + timedelta(minutes=5))
    assert [d.detail["code"] for d in denials(session)] == [
        perm.NO_ACCESS_BASIS,
        perm.NO_VALID_ACCESS_BASIS,
    ]


def test_log_denial_false_writes_nothing(session):
    source = new_source(session)
    perm.check_access(session, source.source_id, Action.READ_POSTS, now=NOW, log_denial=False)
    assert denials(session) == []


# ---------- the gate: require_access and granted_actions ----------


def test_require_access_raises_but_the_denial_record_survives(engine):
    factory = make_session_factory(engine)
    with factory() as s:
        source_id = new_source(s).source_id
        s.commit()
    with pytest.raises(AccessDenied) as caught:
        perm.require_access(factory, source_id, Action.READ_POSTS, now=NOW)
    assert caught.value.decision.code == perm.NO_ACCESS_BASIS
    with factory() as s:  # the audit row was committed before the exception was raised
        assert len(denials(s)) == 1


def test_require_access_returns_the_decision_when_allowed(engine):
    factory = make_session_factory(engine)
    with factory() as s:
        source = new_source(s)
        basis(s, source)
        s.commit()
        source_id = source.source_id
    decision = perm.require_access(factory, source_id, Action.READ_POSTS, now=NOW)
    assert decision.allowed and decision.basis_type == "own_channel"


def test_granted_actions_lists_what_is_allowed_without_logging(session):
    source = new_source(session)
    assert perm.granted_actions(session, source.source_id, now=NOW) == set()
    basis(session, source)
    assert perm.granted_actions(session, source.source_id, now=NOW) == {
        Action.READ_POSTS,
        Action.READ_REACTIONS,
    }
    basis(session, source, AccessBasisType.OTHER_OFFICIAL_API, document_ref="api-terms",
          comments_allowed=True)  # fmt: skip
    assert Action.READ_COMMENTS in perm.granted_actions(session, source.source_id, now=NOW)
    assert denials(session) == []
