"""Collected items, decisions, rechecks, audit samples, dead letters, budgets.

Runs on SQLite and, when reachable, PostgreSQL (see the `engine` fixture).
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sie.storage import repos
from sie.storage import repos_content as rc
from sie.storage.enums import ContentStatus, Outcome
from sie.storage.models import (
    AuditSample,
    BudgetCounter,
    ContentItem,
    DeadLetter,
    Decision,
    PolicyVersion,
    Recheck,
)

NOW = datetime(2026, 11, 10, 8, 41, tzinfo=UTC)


def source(session, external_id="chan"):
    return repos.add_source(session, "telegram", external_id)


def policy(session, version=1):
    session.add(PolicyVersion(version=version, bundle={"policy_version": version}))
    session.flush()
    return version


def item(session, src=None, msg="1", **fields):
    src = src or source(session)
    created_item, _ = rc.upsert_content_item(
        session, source_id=src.source_id, platform_msg_id=msg, published_at=NOW, **fields
    )
    return created_item


# ---------- identity key and idempotent upsert (A-02) ----------


def test_upsert_is_idempotent_on_identity_key(session):
    src = source(session)
    first, created = rc.upsert_content_item(
        session, source_id=src.source_id, platform_msg_id="48213", published_at=NOW,
        text_raw="original text", metrics={"views": 10},
    )  # fmt: skip
    again, created_again = rc.upsert_content_item(
        session, source_id=src.source_id, platform_msg_id="48213", published_at=NOW,
        text_raw="DIFFERENT text", metrics={"views": 999},
    )  # fmt: skip
    session.commit()
    assert created is True and created_again is False
    assert again.item_id == first.item_id
    assert again.text_raw == "original text"  # an existing item is never overwritten
    assert len(session.scalars(select(ContentItem)).all()) == 1


def test_same_message_id_other_kind_or_source_is_a_different_item(session):
    a, b = source(session, "a"), source(session, "b")
    one, _ = rc.upsert_content_item(
        session, source_id=a.source_id, platform_msg_id="7", published_at=NOW
    )
    two, _ = rc.upsert_content_item(
        session, source_id=b.source_id, platform_msg_id="7", published_at=NOW
    )
    three, _ = rc.upsert_content_item(
        session, source_id=a.source_id, platform_msg_id="7", kind="comment", published_at=NOW
    )
    assert len({one.item_id, two.item_id, three.item_id}) == 3


def test_message_ids_are_stored_as_text(session):
    created_item = item(session, msg="123456789012345678")  # larger than 32 bits
    session.commit()
    session.expire_all()
    assert session.get(ContentItem, created_item.item_id).platform_msg_id == "123456789012345678"


def test_content_item_defaults(session):
    created_item = item(session)
    session.commit()
    session.refresh(created_item)
    assert created_item.status == "collected" and created_item.kind == "post"
    assert created_item.metrics == {} and created_item.tenant_id == "default"
    assert created_item.observed_at.tzinfo is not None
    assert created_item.published_at == NOW


# ---------- dropped content is not retained (U-06) ----------


def test_dropped_content_cannot_keep_text(session):
    created_item = item(session, text_raw="secret-ish words", text_norm="secret-ish words")
    session.commit()  # persist first: a failed flush below rolls the whole transaction back
    created_item.status = ContentStatus.DROPPED.value
    with pytest.raises(IntegrityError):  # the database refuses to keep text on a dropped item
        session.flush()
    session.rollback()

    created_item = session.get(ContentItem, created_item.item_id)
    created_item.text_raw = None
    created_item.status = ContentStatus.DROPPED.value
    with pytest.raises(IntegrityError):  # text_norm alone is also retained text
        session.flush()
    session.rollback()

    created_item = session.get(ContentItem, created_item.item_id)
    created_item.text_raw = created_item.text_norm = None
    created_item.status = ContentStatus.DROPPED.value
    session.commit()
    session.refresh(created_item)
    assert created_item.status == "dropped" and created_item.text_norm is None


def test_item_can_be_inserted_as_dropped_only_without_text(session):
    src = source(session)
    with pytest.raises(IntegrityError):
        rc.upsert_content_item(
            session, source_id=src.source_id, platform_msg_id="9", published_at=NOW,
            status="dropped", text_raw="should not be stored",
        )  # fmt: skip
    session.rollback()


@pytest.mark.parametrize(
    "field,value",
    [("kind", "video"), ("status", "weird"), ("lang", "klingon"), ("script", "runes")],
)
def test_enumerated_fields_are_checked(session, field, value):
    src = source(session)
    with pytest.raises(IntegrityError):
        rc.upsert_content_item(
            session,
            source_id=src.source_id,
            platform_msg_id="x",
            published_at=NOW,
            **{field: value},
        )
    session.rollback()


VALID_LANG_SCRIPT = [
    ("uz", "latin"),
    ("ru", "cyrillic"),
    ("mixed", "mixed"),
    ("uz", "cyrillic_to_latin"),
    ("other", None),
]


@pytest.mark.parametrize("lang,script", VALID_LANG_SCRIPT)
def test_valid_language_and_script_values_accepted(session, lang, script):
    item(session, msg=f"{lang}-{script}", lang=lang, script=script)
    session.commit()


def test_item_needs_a_real_source_and_policy_version(session):
    with pytest.raises(IntegrityError):
        rc.upsert_content_item(session, source_id=424242, platform_msg_id="1", published_at=NOW)
    session.rollback()
    src = source(session)
    with pytest.raises(IntegrityError):
        rc.upsert_content_item(
            session,
            source_id=src.source_id,
            platform_msg_id="1",
            published_at=NOW,
            policy_version=99,
        )
    session.rollback()


# ---------- decisions ----------


def test_decision_roundtrip_and_policy_version_must_exist(session):
    version = policy(session)
    created_item = item(session)
    decision = rc.record_decision(
        session, created_item.item_id, version, "p1_topic_from_figure", Outcome.PASS,
        {"matched": ["source_tag", "text_matches_topic"]},
    )  # fmt: skip
    session.commit()
    session.expire_all()
    stored = session.get(Decision, decision.decision_id)
    assert stored.outcome == "PASS" and stored.reasons["matched"][0] == "source_tag"
    assert stored.decided_at.tzinfo is not None

    with pytest.raises(IntegrityError):  # a decision must cite a real policy version
        rc.record_decision(session, created_item.item_id, 777, "default", Outcome.DROP)
    session.rollback()


def test_decision_outcome_is_checked(session):
    version = policy(session)
    created_item = item(session)
    with pytest.raises(IntegrityError):
        rc.record_decision(session, created_item.item_id, version, "r", "MAYBE")
    session.rollback()


def test_deleting_an_item_removes_its_decisions_rechecks_and_samples(session):
    version = policy(session)
    created_item = item(session)
    decision = rc.record_decision(session, created_item.item_id, version, "default", Outcome.DEFER)
    rc.schedule_recheck(session, created_item.item_id, NOW + timedelta(hours=3))
    rc.add_audit_sample(session, created_item.item_id, decision.decision_id, "some text")
    session.commit()
    session.delete(created_item)
    session.commit()
    for model in (Decision, Recheck, AuditSample):
        assert session.scalars(select(model)).all() == []


# ---------- rechecks ----------


def test_recheck_moves_instead_of_duplicating(session):
    created_item = item(session)
    first = rc.schedule_recheck(session, created_item.item_id, NOW + timedelta(hours=1))
    first.attempt = 2
    moved = rc.schedule_recheck(
        session, created_item.item_id, NOW + timedelta(hours=6), max_attempts=5
    )
    session.commit()
    assert moved is first and moved.attempt == 2 and moved.max_attempts == 5
    assert len(session.scalars(select(Recheck)).all()) == 1


@pytest.mark.parametrize("attempt,max_attempts", [(-1, 3), (0, 0), (4, 3)])
def test_recheck_limits_are_checked(session, attempt, max_attempts):
    created_item = item(session)
    session.add(
        Recheck(
            item_id=created_item.item_id, due_at=NOW, attempt=attempt, max_attempts=max_attempts
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# ---------- audit samples and dead letters expire ----------


def test_audit_sample_expires_in_the_future(session):
    version = policy(session)
    created_item = item(session)
    decision = rc.record_decision(session, created_item.item_id, version, "default", Outcome.DROP)
    sample = rc.add_audit_sample(
        session, created_item.item_id, decision.decision_id, "dropped words"
    )
    session.commit()
    session.refresh(sample)
    assert sample.expires_at > sample.created_at
    assert sample.expires_at - sample.created_at < timedelta(days=4)  # default keep: 3 days

    session.add(
        AuditSample(
            item_id=created_item.item_id,
            decision_id=decision.decision_id,
            text_norm="x",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
    )
    with pytest.raises(IntegrityError):  # born already expired is refused
        session.flush()
    session.rollback()


def test_dead_letter_masks_secrets_and_expires(session):
    letter = rc.add_dead_letter(
        session, "normalize", {"text_raw": "hello", "api_hash": "abc123", "meta": {"token": "t"}},
        "boom", keep_days=30,
    )  # fmt: skip
    session.commit()
    session.refresh(letter)
    assert letter.envelope["text_raw"] == "hello"
    assert letter.envelope["api_hash"] == "***" and letter.envelope["meta"]["token"] == "***"
    assert timedelta(days=29) < letter.expires_at - letter.created_at < timedelta(days=31)

    session.add(
        DeadLetter(
            stage="x", envelope={}, error="e", expires_at=datetime.now(UTC) - timedelta(days=1)
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


# ---------- budgets ----------


def test_budget_counter_key_and_checks(session):
    day = date(2026, 11, 10)
    session.add(BudgetCounter(day=day, name="llm_calls", used=5, cap=500))
    session.add(BudgetCounter(day=day, name="fetches", used=0))  # no cap
    session.commit()
    stored = session.get(BudgetCounter, ("default", day, "fetches"))
    assert stored.cap is None and stored.used == 0

    session.add(BudgetCounter(day=day, name="llm_calls", used=1))  # same key again
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    for bad in (dict(used=-1), dict(used=0, cap=-5)):
        session.add(BudgetCounter(day=day, name="bad", **bad))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
