"""String enums shared by models, migrations and business code. Stored as plain text + CHECK."""

from enum import StrEnum


class AccessBasisType(StrEnum):
    """Why we may read a source (TZ CG-1)."""

    TELEGRAM_PERMISSION = "telegram_permission"
    OWNER_CONSENT = "owner_consent"
    OWN_CHANNEL = "own_channel"
    OTHER_OFFICIAL_API = "other_official_api"


class SourceStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"  # e.g. after flood-wait or an access problem (CG-4)
    DISABLED = "disabled"


class PolicyStatus(StrEnum):
    """Draft -> Validate -> Approve -> Publish (TZ 6.4); `retired` = superseded."""

    DRAFT = "draft"
    VALIDATED = "validated"
    APPROVED = "approved"
    PUBLISHED = "published"
    RETIRED = "retired"


def values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


def sql_in(column: str, enum_cls: type[StrEnum]) -> str:
    """`column IN ('a', 'b')` for CHECK constraints (values are code constants, not user input)."""
    quoted = ", ".join(f"'{v}'" for v in values(enum_cls))
    return f"{column} IN ({quoted})"
