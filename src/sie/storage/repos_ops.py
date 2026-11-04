"""Operator task queue: problems that need a human, handled through authorized paths only.

Compliance (CG-4, CG-5): task details are redacted, and the account link must be a plain https
page without credentials or token-like query parameters.
"""

from urllib.parse import parse_qsl, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from sie.logging_setup import SENSITIVE_KEY, redact
from sie.storage.enums import OperatorCategory, OperatorTaskStatus
from sie.storage.models import OperatorTask
from sie.storage.repos import append_audit
from sie.storage.types import utcnow

CLOSED = {OperatorTaskStatus.RESOLVED.value, OperatorTaskStatus.DISMISSED.value}


def validate_account_link(link: str) -> str:
    """Accept only https links with no embedded credentials or token-like parameters."""
    parts = urlsplit(link)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("account link must be an https URL")
    if parts.username or parts.password or "@" in parts.netloc:
        raise ValueError("account link must not contain credentials")
    for key, _value in parse_qsl(parts.query, keep_blank_values=True):
        if SENSITIVE_KEY.search(key):
            raise ValueError(
                f"account link must not carry '{key}' (tokens and sessions are secret)"
            )
    return link


def open_operator_task(
    session: Session,
    category: OperatorCategory | str,
    summary: str,
    *,
    source_id: int | None = None,
    detail: dict | None = None,
    priority: int = 0,
    team: str | None = None,
    account_link: str | None = None,
) -> OperatorTask:
    if len(summary) > 300:
        raise ValueError("summary is limited to 300 characters")
    task = OperatorTask(
        source_id=source_id,
        category=str(category),
        summary=summary,
        detail=redact(detail or {}),
        priority=priority,
        team=team,
        account_link=validate_account_link(account_link) if account_link else None,
    )
    session.add(task)
    session.flush()
    append_audit(
        session,
        "system",
        "operator_task.opened",
        f"operator_task:{task.task_id}",
        {"category": task.category, "source_id": source_id, "priority": priority},
    )
    return task


def resolve_operator_task(
    session: Session,
    task_id: int,
    *,
    resolved_by: str,
    resolution: str,
    dismissed: bool = False,
) -> OperatorTask:
    task = session.get(OperatorTask, task_id)
    if task is None:
        raise LookupError(f"operator_task {task_id} not found")
    if task.status in CLOSED:
        raise ValueError(f"operator_task {task_id} is already {task.status}")
    task.status = (OperatorTaskStatus.DISMISSED if dismissed else OperatorTaskStatus.RESOLVED).value
    task.resolution = resolution
    task.resolved_by = resolved_by
    task.resolved_at = utcnow()
    session.flush()
    append_audit(
        session,
        resolved_by,
        f"operator_task.{task.status}",
        f"operator_task:{task_id}",
        {"resolution": resolution[:200]},
    )
    return task


def list_open_tasks(session: Session, team: str | None = None) -> list[OperatorTask]:
    """Open and in-progress tasks, most urgent first."""
    query = select(OperatorTask).where(OperatorTask.status.not_in(CLOSED))
    if team is not None:
        query = query.where(OperatorTask.team == team)
    return list(session.scalars(query.order_by(OperatorTask.priority.desc(), OperatorTask.task_id)))
