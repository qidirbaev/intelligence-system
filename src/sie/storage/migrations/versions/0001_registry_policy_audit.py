"""registry, access bases, agent state, policy versions, audit log

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Self-contained on purpose: migrations must not change when application code changes.
BIGPK = sa.BigInteger().with_variant(sa.Integer, "sqlite")
JSONT = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def _tenant() -> sa.Column:
    return sa.Column(
        "tenant_id", sa.String(64), nullable=False, server_default=sa.text("'default'")
    )


def _created_at() -> sa.Column:
    return sa.Column("created_at", TS, nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("person_id", BIGPK, primary_key=True, autoincrement=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(64)),
        _tenant(),
        _created_at(),
    )

    op.create_table(
        "sources",
        sa.Column("source_id", BIGPK, primary_key=True, autoincrement=True),
        sa.Column("person_id", BIGPK),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("handle", sa.String(128)),
        sa.Column("tags", JSONT, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        _tenant(),
        _created_at(),
        sa.ForeignKeyConstraint(["person_id"], ["persons.person_id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "platform", "external_id"),
        sa.CheckConstraint("status IN ('active', 'paused', 'disabled')", name="status_valid"),
    )
    op.create_index("ix_sources_person_id", "sources", ["person_id"])

    op.create_table(
        "access_basis",
        sa.Column("basis_id", BIGPK, primary_key=True, autoincrement=True),
        sa.Column("source_id", BIGPK, nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("document_ref", sa.Text),
        sa.Column("comments_allowed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("valid_from", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("valid_to", TS),
        sa.Column("revoked_at", TS),
        _tenant(),
        _created_at(),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "type IN ('telegram_permission', 'owner_consent', 'own_channel', 'other_official_api')",
            name="type_valid",
        ),
        sa.CheckConstraint(
            "type = 'own_channel' OR document_ref IS NOT NULL", name="document_ref_required"
        ),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="validity_order"),
    )
    op.create_index("ix_access_basis_source_id", "access_basis", ["source_id"])

    op.create_table(
        "agent_state",
        sa.Column("source_id", BIGPK, primary_key=True),
        sa.Column("cursor", JSONT, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("next_check_at", TS),
        sa.Column("interval_s", sa.Integer, nullable=False, server_default="300"),
        sa.Column("failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("memory", JSONT, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        _tenant(),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"], ondelete="CASCADE"),
        sa.CheckConstraint("interval_s > 0", name="interval_positive"),
        sa.CheckConstraint("failures >= 0", name="failures_nonnegative"),
    )
    op.create_index("ix_agent_state_next_check_at", "agent_state", ["next_check_at"])

    op.create_table(
        "policy_versions",
        sa.Column("version", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("effective_from", TS),
        sa.Column("bundle", JSONT, nullable=False),
        sa.Column("approved_by", sa.String(128)),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        _tenant(),
        sa.CheckConstraint(
            "status IN ('draft', 'validated', 'approved', 'published', 'retired')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "status NOT IN ('published', 'retired') OR effective_from IS NOT NULL",
            name="published_has_effective_from",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'validated') OR approved_by IS NOT NULL",
            name="approved_has_approver",
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("audit_id", BIGPK, primary_key=True, autoincrement=True),
        sa.Column("ts", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("object", sa.String(128), nullable=False),
        sa.Column("detail", JSONT, nullable=False, server_default=sa.text("'{}'")),
        _tenant(),
    )
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])
    op.create_index("ix_audit_log_object", "audit_log", ["object"])

    if op.get_bind().dialect.name == "postgresql":
        # The audit trail must not be editable: reject UPDATE and DELETE.
        # (TRUNCATE stays possible for development resets.)
        op.execute(
            """
            CREATE FUNCTION audit_log_immutable() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_log is append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_log_no_update_delete
            BEFORE UPDATE OR DELETE ON audit_log
            FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log")
        op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
    op.drop_table("audit_log")
    op.drop_table("policy_versions")
    op.drop_table("agent_state")
    op.drop_table("access_basis")
    op.drop_table("sources")
    op.drop_table("persons")
