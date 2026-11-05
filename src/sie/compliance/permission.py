"""Permission engine: the compliance gate (TZ section 2; requirements CG-1, CG-2, CG-3).

Nothing may read a source unless this engine says yes. It is checked when a fetch is scheduled and
again immediately before it, and it always runs *before* any priority logic (V-08): a high-priority
item never overrides a missing permission.

Rules (default deny):
  * the action must be one an access basis can grant (reading posts, reactions, comments);
    anything else (download_media, profile_commenters, infer_sensitive_traits, unknown) is denied;
  * the source must exist, belong to the configured tenant, and be `active`;
  * at least one access basis must be valid now: not revoked, already in force, not expired;
  * reading comments additionally needs `comments_allowed` on that same basis (CG-3). Consent from
    the channel owner alone never grants comments.

`evaluate_access` is a pure function (no database); `check_access` and `require_access` add the
database and the denial log.
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sie.config import get_settings
from sie.storage.enums import SourceStatus
from sie.storage.models import AccessBasis, AuditLog, Source
from sie.storage.repos import append_audit
from sie.storage.types import utcnow

logger = logging.getLogger("sie.compliance")

# One persistent audit record per (source, action, reason) per window; every denial is still
# written to the application log. Keeps the audit trail readable when a scheduler retries.
DEFAULT_DEDUPE_MINUTES = 60


class Action(StrEnum):
    """Things the system may be asked to do with a source (names match TZ section 6 policies)."""

    READ_POSTS = "read_posts"
    READ_COMMENTS = "read_comments"
    READ_REACTIONS = "read_reactions"
    DOWNLOAD_MEDIA = "download_media"
    PROFILE_COMMENTERS = "profile_commenters"
    INFER_SENSITIVE_TRAITS = "infer_sensitive_traits"


# The only actions an access basis can grant. Everything else is denied by default.
GRANTABLE_BY_BASIS = frozenset({Action.READ_POSTS, Action.READ_REACTIONS, Action.READ_COMMENTS})

# Denial codes (stable strings: they are stored in the audit log).
ALLOWED = "allowed"
ACTION_NOT_SUPPORTED = "action_not_supported"
UNKNOWN_SOURCE = "unknown_source"
TENANT_MISMATCH = "tenant_mismatch"
SOURCE_PAUSED = "source_paused"
SOURCE_DISABLED = "source_disabled"
NO_ACCESS_BASIS = "no_access_basis"
NO_VALID_ACCESS_BASIS = "no_valid_access_basis"
COMMENTS_NOT_ALLOWED = "comments_not_allowed"


class SourceLike(Protocol):
    source_id: int
    tenant_id: str
    status: str


class BasisLike(Protocol):
    basis_id: int
    type: str
    tenant_id: str
    comments_allowed: bool
    valid_from: datetime
    valid_to: datetime | None
    revoked_at: datetime | None


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    action: str
    source_id: int
    code: str
    reasons: tuple[str, ...] = ()
    basis_id: int | None = None  # the basis that granted access, when allowed
    basis_type: str | None = None


class AccessDenied(PermissionError):
    """Raised by `require_access` when the engine says no. Carries the decision."""

    def __init__(self, decision: PermissionDecision) -> None:
        self.decision = decision
        why = "; ".join(decision.reasons) or decision.code
        super().__init__(
            f"access denied ({decision.code}): {decision.action} "
            f"on source {decision.source_id}: {why}"
        )


def _deny(source_id: int, action: str, code: str, *reasons: str) -> PermissionDecision:
    return PermissionDecision(False, action, source_id, code, tuple(reasons))


def _validity_problems(basis: BasisLike, now: datetime) -> list[str]:
    problems = []
    if basis.revoked_at is not None:
        problems.append("revoked")
    if basis.valid_from > now:
        problems.append("not yet valid")
    if basis.valid_to is not None and now >= basis.valid_to:
        problems.append("expired")
    return problems


def evaluate_access(
    source: SourceLike | None,
    bases: Iterable[BasisLike],
    action: Action | str,
    *,
    source_id: int,
    now: datetime,
    tenant_id: str,
) -> PermissionDecision:
    """Decide whether `action` on the source is permitted right now. Pure: no database, no clock."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware (UTC)")
    try:
        act = Action(action)
    except ValueError:
        return _deny(source_id, str(action), ACTION_NOT_SUPPORTED, "unknown action")
    name = act.value

    if act not in GRANTABLE_BY_BASIS:
        return _deny(
            source_id, name, ACTION_NOT_SUPPORTED,
            "an access basis cannot grant this action (denied by default)",
        )  # fmt: skip
    if source is None:
        return _deny(source_id, name, UNKNOWN_SOURCE, "no such source")
    if source.tenant_id != tenant_id:
        return _deny(source_id, name, TENANT_MISMATCH, "source belongs to another tenant")
    if source.status == SourceStatus.PAUSED.value:
        return _deny(source_id, name, SOURCE_PAUSED, "source is paused")
    if source.status != SourceStatus.ACTIVE.value:
        return _deny(source_id, name, SOURCE_DISABLED, f"source status is '{source.status}'")

    own_bases = [b for b in bases if b.tenant_id == source.tenant_id]
    if not own_bases:
        return _deny(
            source_id, name, NO_ACCESS_BASIS, "no access basis is recorded for this source"
        )

    reasons: list[str] = []
    lacks_comments_only = False
    for basis in sorted(own_bases, key=lambda b: b.basis_id):
        problems = _validity_problems(basis, now)
        if not problems and act is Action.READ_COMMENTS and not basis.comments_allowed:
            lacks_comments_only = True
            problems = ["comments not allowed"]
        if not problems:
            return PermissionDecision(
                True, name, source_id, ALLOWED, (), basis.basis_id, str(basis.type)
            )
        reasons.append(f"basis {basis.basis_id} ({basis.type}): {', '.join(problems)}")

    code = COMMENTS_NOT_ALLOWED if lacks_comments_only else NO_VALID_ACCESS_BASIS
    return _deny(source_id, name, code, *reasons)


def _log_denial(
    session: Session, decision: PermissionDecision, now: datetime, dedupe_minutes: int
) -> bool:
    """Application log: always. Audit log: once per window. True if an audit row was added."""
    logger.warning(
        "access denied",
        extra={
            "source_id": decision.source_id,
            "action": decision.action,
            "code": decision.code,
            "reasons": list(decision.reasons),
        },
    )
    object_ref = f"source:{decision.source_id}"
    recent = session.scalars(
        select(AuditLog.detail).where(
            AuditLog.object == object_ref,
            AuditLog.action == "access.denied",
            AuditLog.ts >= now - timedelta(minutes=dedupe_minutes),
        )
    ).all()
    if any(d.get("action") == decision.action and d.get("code") == decision.code for d in recent):
        return False
    append_audit(
        session,
        "system",
        "access.denied",
        object_ref,
        {"action": decision.action, "code": decision.code, "reasons": list(decision.reasons)},
        ts=now,
    )
    return True


def check_access(
    session: Session,
    source_id: int,
    action: Action | str,
    *,
    now: datetime | None = None,
    log_denial: bool = True,
    dedupe_minutes: int = DEFAULT_DEDUPE_MINUTES,
) -> PermissionDecision:
    """Look up the source and its bases and decide. Never raises on denial.

    A denial is written to the audit log inside *your* transaction: commit it. If you raise and
    roll back, the audit row is lost; use `require_access`, which owns its transaction.
    """
    now = now or utcnow()
    source = session.get(Source, source_id)
    bases: Sequence[AccessBasis] = (
        list(session.scalars(select(AccessBasis).where(AccessBasis.source_id == source_id)))
        if source is not None
        else []
    )
    decision = evaluate_access(
        source, bases, action, source_id=source_id, now=now, tenant_id=get_settings().tenant_id
    )
    if not decision.allowed and log_denial:
        _log_denial(session, decision, now, dedupe_minutes)
    return decision


def require_access(
    factory: sessionmaker[Session],
    source_id: int,
    action: Action | str,
    *,
    now: datetime | None = None,
    dedupe_minutes: int = DEFAULT_DEDUPE_MINUTES,
) -> PermissionDecision:
    """The gate to call before any read: checks in its own transaction, then raises on denial.

    The transaction is committed *before* raising, so the denial record survives the exception.
    """
    with factory() as session:
        decision = check_access(session, source_id, action, now=now, dedupe_minutes=dedupe_minutes)
        session.commit()
    if not decision.allowed:
        raise AccessDenied(decision)
    return decision


def granted_actions(
    session: Session, source_id: int, *, now: datetime | None = None
) -> set[Action]:
    """Which read actions are currently allowed (for the scheduler). Writes no audit rows."""
    return {
        action
        for action in GRANTABLE_BY_BASIS
        if check_access(session, source_id, action, now=now, log_denial=False).allowed
    }
