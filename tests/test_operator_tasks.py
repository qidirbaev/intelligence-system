"""The operator task queue (requirements V-09, CG-4, CG-5)."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sie.storage import repos
from sie.storage import repos_ops as ops
from sie.storage.enums import OperatorCategory
from sie.storage.models import AuditLog, OperatorTask


def src(session):
    return repos.add_source(session, "telegram", "chan")


def test_operator_task_lifecycle_is_audited(session):
    source = src(session)
    task = ops.open_operator_task(
        session, OperatorCategory.FLOOD_WAIT, "Telegram asked us to wait 3600 s",
        source_id=source.source_id, priority=5, team="team-a",
        detail={"wait_seconds": 3600},
    )  # fmt: skip
    session.commit()
    session.refresh(task)
    assert task.status == "open" and task.priority == 5 and task.created_at.tzinfo is not None

    ops.resolve_operator_task(
        session, task.task_id, resolved_by="operator:ann", resolution="waited"
    )
    session.commit()
    session.refresh(task)
    assert task.status == "resolved" and task.resolved_by == "operator:ann"
    assert task.resolved_at.tzinfo is not None
    actions = session.scalars(select(AuditLog.action).order_by(AuditLog.audit_id)).all()
    assert actions == ["operator_task.opened", "operator_task.resolved"]


def test_dismissing_and_double_closing(session):
    task = ops.open_operator_task(session, "other", "not actionable")
    ops.resolve_operator_task(
        session, task.task_id, resolved_by="ann", resolution="noise", dismissed=True
    )
    assert task.status == "dismissed"
    with pytest.raises(ValueError, match="already"):
        ops.resolve_operator_task(session, task.task_id, resolved_by="bob", resolution="again")
    with pytest.raises(LookupError):
        ops.resolve_operator_task(session, 999, resolved_by="x", resolution="y")


def test_operator_task_never_stores_secrets(session):
    detail = {
        "api_hash": "abc",
        "session_string": "SECRET",
        "nested": {"password": "p"},
        "note": "ok",
    }
    task = ops.open_operator_task(session, "session_revoked", "session ended", detail=detail)
    session.commit()
    session.refresh(task)
    assert task.detail["api_hash"] == "***" and task.detail["session_string"] == "***"
    assert task.detail["nested"]["password"] == "***" and task.detail["note"] == "ok"
    assert "SECRET" not in str(task.detail)


@pytest.mark.parametrize(
    "link",
    [
        "http://example.org/recover",  # not https
        "https://user:pass@example.org/recover",  # credentials in the URL
        "https://example.org/recover?token=abc",  # token-like parameter
        "https://example.org/x?session=abc",
        "ftp://example.org/x",
        "not a url",
    ],
)
def test_unsafe_account_links_are_refused(session, link):
    with pytest.raises(ValueError):
        ops.open_operator_task(session, "access_denied", "needs recovery", account_link=link)


def test_safe_account_link_is_kept(session):
    task = ops.open_operator_task(
        session, "access_denied", "needs recovery", account_link="https://telegram.org/support"
    )
    assert task.account_link == "https://telegram.org/support"


def test_database_also_refuses_non_https_links_and_unexplained_closing(session):
    session.add(OperatorTask(category="other", summary="x", account_link="http://insecure.example"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    task = ops.open_operator_task(session, "other", "closing without a resolver")
    task.status = "resolved"  # no resolved_by / resolved_at
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_category_and_status_are_checked(session):
    session.add(OperatorTask(category="solve_the_captcha_for_me", summary="x"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
    session.add(OperatorTask(category="other", summary="x", status="stuck"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_summary_length_is_limited(session):
    with pytest.raises(ValueError, match="300"):
        ops.open_operator_task(session, "other", "x" * 301)


def test_open_tasks_are_listed_most_urgent_first_and_by_team(session):
    low = ops.open_operator_task(session, "other", "low", priority=1, team="a")
    high = ops.open_operator_task(session, "other", "high", priority=9, team="b")
    done = ops.open_operator_task(session, "other", "done", priority=99, team="a")
    ops.resolve_operator_task(session, done.task_id, resolved_by="ann", resolution="ok")
    assert [t.task_id for t in ops.list_open_tasks(session)] == [high.task_id, low.task_id]
    assert [t.task_id for t in ops.list_open_tasks(session, team="a")] == [low.task_id]


def test_task_may_have_no_source(session):
    task = ops.open_operator_task(session, "other", "system-wide problem")
    assert task.source_id is None


def test_source_with_tasks_cannot_be_deleted(session):
    source = src(session)
    ops.open_operator_task(session, "account_banned", "banned", source_id=source.source_id)
    session.commit()
    session.delete(source)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
