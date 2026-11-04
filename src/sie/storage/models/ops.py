"""Operational tables: budgets and the operator task queue (human help for access problems)."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from sie.storage.base import Base
from sie.storage.enums import OperatorCategory, OperatorTaskStatus, sql_in
from sie.storage.models.common import CreatedAtMixin, TenantMixin
from sie.storage.types import BigIntPK, JSONType, UTCDateTime


class BudgetCounter(TenantMixin, Base):
    """Daily usage counters (LLM calls, fetches...) against caps (TZ 5.9, 11)."""

    __tablename__ = "budget_counters"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "day", "name"),
        CheckConstraint("used >= 0", name="used_nonnegative"),
        CheckConstraint("cap IS NULL OR cap >= 0", name="cap_nonnegative"),
    )

    day: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    cap: Mapped[int | None] = mapped_column(BigInteger)  # NULL = no cap


class OperatorTask(TenantMixin, CreatedAtMixin, Base):
    """A problem that needs a human (TZ 13): flood wait, revoked session, challenge, ban...

    Compliance (CG-4, CG-5): the task never carries credentials or session data, and the optional
    account link must be an https page of the platform's own authorized recovery path.
    """

    __tablename__ = "operator_tasks"
    __table_args__ = (
        CheckConstraint(sql_in("category", OperatorCategory), name="category_valid"),
        CheckConstraint(sql_in("status", OperatorTaskStatus), name="status_valid"),
        CheckConstraint(
            "account_link IS NULL OR substr(account_link, 1, 8) = 'https://'", name="link_is_https"
        ),
        CheckConstraint(
            "status NOT IN ('resolved', 'dismissed') "
            "OR (resolved_at IS NOT NULL AND resolved_by IS NOT NULL)",
            name="closed_has_resolver",
        ),
        Index("ix_operator_tasks_status_priority", "status", "priority"),
        Index("ix_operator_tasks_source_id", "source_id"),
    )

    task_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.source_id", ondelete="RESTRICT")
    )  # NULL for system-wide problems
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=OperatorTaskStatus.OPEN.value,
        server_default="open",
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    team: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    detail: Mapped[dict] = mapped_column(
        JSONType, nullable=False, default=dict, server_default=text("'{}'")
    )  # redacted by the repository; never credentials
    account_link: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(128))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


__all__ = ["BudgetCounter", "OperatorTask"]
