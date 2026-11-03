"""Pieces shared by all models."""

from datetime import datetime

from sqlalchemy import String, func, text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from sie.config import get_settings
from sie.storage.types import UTCDateTime


def current_tenant() -> str:
    """Python-side default for tenant_id (a single fixed value in the MVP)."""
    return get_settings().tenant_id


class TenantMixin:
    """Every table carries tenant_id so multi-tenancy stays possible later (TZ section 4)."""

    @declared_attr
    def tenant_id(cls) -> Mapped[str]:
        return mapped_column(
            String(64), nullable=False, default=current_tenant, server_default=text("'default'")
        )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, server_default=func.now()
    )
