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


class ContentKind(StrEnum):
    POST = "post"
    COMMENT = "comment"  # comments are not stored as items by default (TZ section 7)


class ContentStatus(StrEnum):
    """Lifecycle of an item (TZ 20.3). `dropped` items hold no text (requirement U-06)."""

    COLLECTED = "collected"
    DEFERRED = "deferred"
    PASSED = "passed"
    DROPPED = "dropped"
    ANALYZED = "analyzed"


class Outcome(StrEnum):
    """L0 decision outcomes (TZ 5.4)."""

    PASS = "PASS"
    DEFER = "DEFER"
    DROP = "DROP"
    REQUEST_LIMITED = "REQUEST_LIMITED"


class Lang(StrEnum):
    UZ = "uz"
    RU = "ru"
    MIXED = "mixed"
    OTHER = "other"


class Script(StrEnum):
    LATIN = "latin"
    CYRILLIC = "cyrillic"
    CYRILLIC_TO_LATIN = "cyrillic_to_latin"
    MIXED = "mixed"


class OperatorCategory(StrEnum):
    """Why a human is needed (CG-4). Humans use authorized paths only, never raw credentials."""

    FLOOD_WAIT = "flood_wait"
    ACCESS_DENIED = "access_denied"
    SESSION_REVOKED = "session_revoked"
    CHALLENGE_REQUIRED = "challenge_required"
    ACCOUNT_BANNED = "account_banned"
    OTHER = "other"


class OperatorTaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


def values(enum_cls: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_cls]


def sql_in(column: str, enum_cls: type[StrEnum]) -> str:
    """`column IN ('a', 'b')` for CHECK constraints (values are code constants, not user input)."""
    quoted = ", ".join(f"'{v}'" for v in values(enum_cls))
    return f"{column} IN ({quoted})"
