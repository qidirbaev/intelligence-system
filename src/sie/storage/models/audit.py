"""Append-only audit log (TZ section 4). On PostgreSQL a trigger forbids UPDATE/DELETE."""

from datetime import datetime

from sqlalchemy import Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from sie.storage.base import Base
from sie.storage.models.common import TenantMixin
from sie.storage.types import BigIntPK, JSONType, UTCDateTime


class AuditLog(TenantMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_ts", "ts"), Index("ix_audit_log_object", "object"))

    audit_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, server_default=func.now())
    actor: Mapped[str] = mapped_column(String(128), nullable=False)  # user, service or 'system'
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. basis.revoked
    object: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. access_basis:12
    detail: Mapped[dict] = mapped_column(
        JSONType, nullable=False, default=dict, server_default=text("'{}'")
    )
