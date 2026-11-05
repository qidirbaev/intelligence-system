"""Small data-access helpers for the registry tables. Callers own the transaction."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from sie.config import get_settings
from sie.storage.enums import AccessBasisType
from sie.storage.models import AccessBasis, AgentState, AuditLog, Person, Source
from sie.storage.types import utcnow


def add_person(session: Session, display_name: str, category: str | None = None) -> Person:
    person = Person(display_name=display_name, category=category)
    session.add(person)
    session.flush()
    return person


def add_source(
    session: Session,
    platform: str,
    external_id: str,
    *,
    handle: str | None = None,
    person_id: int | None = None,
    tags: list[str] | None = None,
    priority: int = 0,
) -> Source:
    """Create a source and its agent_state row (one logical agent per source)."""
    source = Source(
        platform=platform,
        external_id=external_id,
        handle=handle,
        person_id=person_id,
        tags=list(tags or []),
        priority=priority,
    )
    source.agent_state = AgentState()
    session.add(source)
    session.flush()
    return source


def get_source(session: Session, platform: str, external_id: str) -> Source | None:
    return session.scalar(
        select(Source).where(
            Source.tenant_id == get_settings().tenant_id,
            Source.platform == platform,
            Source.external_id == external_id,
        )
    )


def add_access_basis(
    session: Session,
    source_id: int,
    type: AccessBasisType | str,
    *,
    document_ref: str | None = None,
    comments_allowed: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> AccessBasis:
    basis = AccessBasis(
        source_id=source_id,
        type=str(type),
        document_ref=document_ref,
        comments_allowed=comments_allowed,
        valid_from=valid_from or utcnow(),
        valid_to=valid_to,
    )
    session.add(basis)
    session.flush()
    append_audit(
        session,
        "system",
        "basis.created",
        f"access_basis:{basis.basis_id}",
        {"source_id": source_id, "type": str(type), "comments_allowed": comments_allowed},
    )
    return basis


def list_access_bases(session: Session, source_id: int) -> list[AccessBasis]:
    return list(
        session.scalars(
            select(AccessBasis)
            .where(AccessBasis.source_id == source_id)
            .order_by(AccessBasis.basis_id)
        )
    )


def revoke_access_basis(
    session: Session, basis_id: int, *, actor: str = "system", at: datetime | None = None
) -> AccessBasis:
    """Mark a basis revoked (kept for the record, never deleted) and audit it."""
    basis = session.get(AccessBasis, basis_id)
    if basis is None:
        raise LookupError(f"access_basis {basis_id} not found")
    if basis.revoked_at is None:
        basis.revoked_at = at or utcnow()
        session.flush()
        append_audit(
            session,
            actor,
            "basis.revoked",
            f"access_basis:{basis_id}",
            {"source_id": basis.source_id},
        )
    return basis


def append_audit(
    session: Session,
    actor: str,
    action: str,
    object_ref: str,
    detail: dict | None = None,
    *,
    ts: datetime | None = None,
) -> AuditLog:
    """Append an audit entry. `ts` defaults to the database clock; tests may pass a time."""
    entry = AuditLog(actor=actor, action=action, object=object_ref, detail=detail or {})
    if ts is not None:
        entry.ts = ts
    session.add(entry)
    session.flush()
    return entry
