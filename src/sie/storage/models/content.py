"""Collected items, L0 decisions, rechecks, audit samples and dead letters (TZ sections 4-5)."""

from datetime import datetime

from sqlalchemy import (
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
from sqlalchemy.orm import Mapped, mapped_column

from sie.storage.base import Base
from sie.storage.enums import ContentKind, ContentStatus, Lang, Outcome, Script, sql_in
from sie.storage.models.common import CreatedAtMixin, TenantMixin
from sie.storage.types import BigIntPK, JSONType, UTCDateTime


class ContentItem(TenantMixin, Base):
    """One collected post (or comment). Identity: source_id + platform_msg_id + kind (TZ 5.1)."""

    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("source_id", "platform_msg_id", "kind"),
        CheckConstraint(sql_in("kind", ContentKind), name="kind_valid"),
        CheckConstraint(sql_in("status", ContentStatus), name="status_valid"),
        CheckConstraint("lang IS NULL OR " + sql_in("lang", Lang), name="lang_valid"),
        CheckConstraint("script IS NULL OR " + sql_in("script", Script), name="script_valid"),
        # Requirement U-06: dropped content is not retained. The schema itself enforces it.
        CheckConstraint(
            "status <> 'dropped' OR (text_raw IS NULL AND text_norm IS NULL)",
            name="dropped_has_no_text",
        ),
        Index("ix_content_items_source_published", "source_id", "published_at"),
        Index("ix_content_items_status", "status"),
    )

    item_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.source_id", ondelete="RESTRICT"), nullable=False
    )
    platform_msg_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ContentKind.POST.value, server_default="post"
    )
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now()
    )
    lang: Mapped[str | None] = mapped_column(String(8))
    script: Mapped[str | None] = mapped_column(String(24))
    text_raw: Mapped[str | None] = mapped_column(Text)  # nulled on DROP
    text_norm: Mapped[str | None] = mapped_column(Text)  # nulled on DROP
    simhash: Mapped[str | None] = mapped_column(String(16))  # 64-bit hash as hex
    metrics: Mapped[dict] = mapped_column(
        JSONType, nullable=False, default=dict, server_default=text("'{}'")
    )  # views, reactions, observed_at of the snapshot
    policy_version: Mapped[int | None] = mapped_column(
        ForeignKey("policy_versions.version", ondelete="RESTRICT")
    )  # version of the latest decision
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ContentStatus.COLLECTED.value,
        server_default="collected",
    )


class Decision(TenantMixin, Base):
    """Log of every L0 decision: which policy version, which rule, what outcome, why."""

    __tablename__ = "decisions"
    __table_args__ = (
        CheckConstraint(sql_in("outcome", Outcome), name="outcome_valid"),
        Index("ix_decisions_item_id", "item_id"),
        Index("ix_decisions_policy_version", "policy_version"),
    )

    decision_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("content_items.item_id", ondelete="CASCADE"), nullable=False
    )
    policy_version: Mapped[int] = mapped_column(
        ForeignKey("policy_versions.version", ondelete="RESTRICT"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    reasons: Mapped[dict] = mapped_column(
        JSONType, nullable=False, default=dict, server_default=text("'{}'")
    )
    decided_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now()
    )


class Recheck(TenantMixin, Base):
    """A DEFERred item waiting for a later check. Re-evaluated under the *current* policy."""

    __tablename__ = "rechecks"
    __table_args__ = (
        CheckConstraint("attempt >= 0", name="attempt_nonnegative"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        CheckConstraint("attempt <= max_attempts", name="attempt_within_max"),
        Index("ix_rechecks_due_at", "due_at"),
    )

    item_id: Mapped[int] = mapped_column(
        ForeignKey("content_items.item_id", ondelete="CASCADE"), primary_key=True
    )
    due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )


class AuditSample(TenantMixin, CreatedAtMixin, Base):
    """Tiny, short-lived copy of dropped text, used only to estimate L0 recall (TZ 5.5).

    L1 and the Brain must never read this table (enforced by tests/test_conformance.py).
    """

    __tablename__ = "audit_samples"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        Index("ix_audit_samples_expires_at", "expires_at"),
    )

    sample_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("content_items.item_id", ondelete="CASCADE"), nullable=False
    )
    decision_id: Mapped[int] = mapped_column(
        ForeignKey("decisions.decision_id", ondelete="CASCADE"), nullable=False
    )
    text_norm: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class DeadLetter(TenantMixin, CreatedAtMixin, Base):
    """An envelope that could not be processed. Expires so failed content is not kept forever."""

    __tablename__ = "dead_letters"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        Index("ix_dead_letters_expires_at", "expires_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    envelope: Mapped[dict] = mapped_column(JSONType, nullable=False)
    error: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
