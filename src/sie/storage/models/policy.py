"""Versioned policy bundles (TZ section 6)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from sie.storage.base import Base
from sie.storage.enums import PolicyStatus, sql_in
from sie.storage.models.common import TenantMixin
from sie.storage.types import JSONType, UTCDateTime


class PolicyVersion(TenantMixin, Base):
    __tablename__ = "policy_versions"
    __table_args__ = (
        CheckConstraint(sql_in("status", PolicyStatus), name="status_valid"),
        # Published/retired versions must have an effective time and an approver (TZ 6.6).
        CheckConstraint(
            "status NOT IN ('published', 'retired') OR effective_from IS NOT NULL",
            name="published_has_effective_from",
        ),
        CheckConstraint(
            "status IN ('draft', 'validated') OR approved_by IS NOT NULL",
            name="approved_has_approver",
        ),
    )

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=PolicyStatus.DRAFT.value, server_default="draft"
    )
    effective_from: Mapped[datetime | None] = mapped_column(UTCDateTime)
    bundle: Mapped[dict] = mapped_column(JSONType, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now()
    )
