"""Data access for collected items, decisions, rechecks, audit samples and dead letters.

Helpers flush but never commit; the caller owns the transaction.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from sie.logging_setup import redact
from sie.storage.models import AuditSample, ContentItem, DeadLetter, Decision, Recheck
from sie.storage.types import utcnow

_IDENTITY = ("source_id", "platform_msg_id", "kind")


def _insert_for(session: Session):
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover
        raise NotImplementedError(f"unsupported database: {dialect}")
    return insert


def upsert_content_item(
    session: Session,
    *,
    source_id: int,
    platform_msg_id: str,
    published_at: datetime,
    kind: str = "post",
    observed_at: datetime | None = None,
    **fields,
) -> tuple[ContentItem, bool]:
    """Insert the item unless its identity key already exists. Returns (item, created).

    Idempotent and race-safe (the unique constraint decides). An existing item is returned
    untouched: reprocessing the same message never overwrites or duplicates it (requirement A-02).
    """
    values = {
        "source_id": source_id,
        "platform_msg_id": str(platform_msg_id),
        "kind": str(kind),
        "published_at": published_at,
        "observed_at": observed_at or utcnow(),
        **fields,
    }
    statement = (
        _insert_for(session)(ContentItem)
        .values(**values)
        .on_conflict_do_nothing(index_elements=list(_IDENTITY))
        .returning(ContentItem.item_id)
    )
    new_id = session.execute(statement).scalar_one_or_none()
    if new_id is not None:
        return session.get(ContentItem, new_id), True
    existing = session.scalars(
        select(ContentItem).where(
            ContentItem.source_id == source_id,
            ContentItem.platform_msg_id == str(platform_msg_id),
            ContentItem.kind == str(kind),
        )
    ).one()
    return existing, False


def record_decision(
    session: Session,
    item_id: int,
    policy_version: int,
    rule_id: str,
    outcome: str,
    reasons: dict | None = None,
) -> Decision:
    decision = Decision(
        item_id=item_id,
        policy_version=policy_version,
        rule_id=rule_id,
        outcome=str(outcome),
        reasons=reasons or {},
    )
    session.add(decision)
    session.flush()
    return decision


def schedule_recheck(
    session: Session, item_id: int, due_at: datetime, *, max_attempts: int = 3
) -> Recheck:
    """Create the recheck, or move the existing one (attempts are kept)."""
    recheck = session.get(Recheck, item_id)
    if recheck is None:
        recheck = Recheck(item_id=item_id, due_at=due_at, max_attempts=max_attempts)
        session.add(recheck)
    else:
        recheck.due_at = due_at
        recheck.max_attempts = max_attempts
    session.flush()
    return recheck


def add_audit_sample(
    session: Session, item_id: int, decision_id: int, text_norm: str, *, keep_days: int = 3
) -> AuditSample:
    sample = AuditSample(
        item_id=item_id,
        decision_id=decision_id,
        text_norm=text_norm,
        expires_at=utcnow() + timedelta(days=keep_days),
    )
    session.add(sample)
    session.flush()
    return sample


def add_dead_letter(
    session: Session, stage: str, envelope: dict, error: str, *, keep_days: int = 30
) -> DeadLetter:
    """Park a failed envelope. Secret-looking fields are masked (CG-5); it expires (CG-7)."""
    letter = DeadLetter(
        stage=stage,
        envelope=redact(envelope),
        error=error,
        expires_at=utcnow() + timedelta(days=keep_days),
    )
    session.add(letter)
    session.flush()
    return letter
