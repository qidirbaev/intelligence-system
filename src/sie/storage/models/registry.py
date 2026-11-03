"""Persons, sources, access bases (compliance gate) and per-source agent state."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sie.storage.base import Base
from sie.storage.enums import AccessBasisType, SourceStatus, sql_in
from sie.storage.models.common import CreatedAtMixin, TenantMixin
from sie.storage.types import BigIntPK, JSONType, UTCDateTime


class Person(TenantMixin, CreatedAtMixin, Base):
    """A real person or organisation; one person may own several source accounts."""

    __tablename__ = "persons"

    person_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64))  # e.g. politician, blogger

    sources: Mapped[list["Source"]] = relationship(back_populates="person")


class Source(TenantMixin, CreatedAtMixin, Base):
    """An external channel/account. One logical agent per source (TZ 4.2)."""

    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", "external_id"),
        CheckConstraint(sql_in("status", SourceStatus), name="status_valid"),
        Index("ix_sources_person_id", "person_id"),
    )

    source_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    person_id: Mapped[int | None] = mapped_column(
        ForeignKey("persons.person_id", ondelete="SET NULL")
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)  # telegram, threads, ...
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)  # platform's own id
    handle: Mapped[str | None] = mapped_column(String(128))
    tags: Mapped[list[str]] = mapped_column(
        JSONType, nullable=False, default=list, server_default=text("'[]'")
    )  # e.g. ["public_figure", "priority_figure"]
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SourceStatus.ACTIVE.value, server_default="active"
    )

    person: Mapped[Person | None] = relationship(back_populates="sources")
    access_bases: Mapped[list["AccessBasis"]] = relationship(back_populates="source")
    agent_state: Mapped["AgentState | None"] = relationship(
        back_populates="source", cascade="all, delete-orphan", passive_deletes=True
    )


class AccessBasis(TenantMixin, CreatedAtMixin, Base):
    """Documented reason we may read a source (CG-1). No valid basis -> no reading."""

    __tablename__ = "access_basis"
    __table_args__ = (
        CheckConstraint(sql_in("type", AccessBasisType), name="type_valid"),
        CheckConstraint(
            "type = 'own_channel' OR document_ref IS NOT NULL", name="document_ref_required"
        ),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="validity_order"),
        Index("ix_access_basis_source_id", "source_id"),
    )

    basis_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.source_id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    document_ref: Mapped[str | None] = mapped_column(Text)  # permission letter / consent file id
    comments_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )  # CG-3: default deny
    valid_from: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    source: Mapped[Source] = relationship(back_populates="access_bases")


class AgentState(TenantMixin, Base):
    """Durable state of a logical agent: survives worker restarts (TZ 3.4)."""

    __tablename__ = "agent_state"
    __table_args__ = (
        CheckConstraint("interval_s > 0", name="interval_positive"),
        CheckConstraint("failures >= 0", name="failures_nonnegative"),
        Index("ix_agent_state_next_check_at", "next_check_at"),
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.source_id", ondelete="CASCADE"), primary_key=True
    )
    cursor: Mapped[dict] = mapped_column(
        JSONType, nullable=False, default=dict, server_default=text("'{}'")
    )
    next_check_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    interval_s: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300, server_default="300"
    )
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    memory: Mapped[dict] = mapped_column(
        JSONType, nullable=False, default=dict, server_default=text("'{}'")
    )  # M1-M3 (TZ 3.4)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now()
    )

    source: Mapped[Source] = relationship(back_populates="agent_state")
