"""Column types that behave the same on PostgreSQL and SQLite."""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON, TypeDecorator

# BIGINT primary keys on PostgreSQL; plain INTEGER on SQLite so autoincrement works.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")

# JSONB on PostgreSQL, JSON elsewhere.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes only.

    Naive datetimes are rejected on write (they hide bugs); values read back from SQLite,
    which drops the offset, are returned as UTC-aware.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime not allowed; use timezone-aware UTC (sie.storage.types.utcnow)"
            )
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
