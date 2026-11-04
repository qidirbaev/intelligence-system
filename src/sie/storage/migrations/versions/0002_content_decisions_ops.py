"""content items, decisions, rechecks, audit samples, dead letters, budgets, operator tasks

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
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
        "content_items",
        sa.Column("item_id", BIGPK, primary_key=True, autoincrement=True),
        sa.Column("source_id", BIGPK, nullable=False),
        sa.Column("platform_msg_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="post"),
        sa.Column("published_at", TS, nullable=False),
        sa.Column("observed_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("lang", sa.String(8)),
        sa.Column("script", sa.String(24)),
        sa.Column("text_raw", sa.Text),
        sa.Column("text_norm", sa.Text),
        sa.Column("simhash", sa.String(16)),
        sa.Column("metrics", JSONT, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("policy_version", sa.Integer),
        sa.Column("status", sa.String(16), nullable=False, server_default="collected"),
        _tenant(),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["policy_version"], ["policy_versions.version"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("source_id", "platform_msg_id", "kind"),
        sa.CheckConstraint("kind IN ('post', 'comment')", name="kind_valid"),
        sa.CheckConstraint(
            "status IN ('collected', 'deferred', 'passed', 'dropped', 'analyzed')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "lang IS NULL OR lang IN ('uz', 'ru', 'mixed', 'other')", name="lang_valid"
        ),
        sa.CheckConstraint(
            "script IS NULL OR script IN ('latin', 'cyrillic', 'cyrillic_to_latin', 'mixed')",
            name="script_valid",
        ),
        sa.CheckConstraint(
            "status <> 'dropped' OR (text_raw IS NULL AND text_norm IS NULL)",
            name="dropped_has_no_text",
        ),
    )
    op.create_index(
        "ix_content_items_source_published", "content_items", ["source_id", "published_at"]
    )
    op.create_index("ix_content_items_status", "content_items", ["status"])

    op.create_table(
        "decisions",
        sa.Column("decision_id", BIGPK, primary_key=True, autoincrement=True),
        sa.Column("item_id", BIGPK, nullable=False),
        sa.Column("policy_version", sa.Integer, nullable=False),
        sa.Column("rule_id", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("reasons", JSONT, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("decided_at", TS, nullable=False, server_default=sa.func.now()),
        _tenant(),
        sa.ForeignKeyConstraint(["item_id"], ["content_items.item_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["policy_version"], ["policy_versions.version"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "outcome IN ('PASS', 'DEFER', 'DROP', 'REQUEST_LIMITED')", name="outcome_valid"
        ),
    )
    op.create_index("ix_decisions_item_id", "decisions", ["item_id"])
    op.create_index("ix_decisions_policy_version", "decisions", ["policy_version"])

    op.create_table(
        "rechecks",
        sa.Column("item_id", BIGPK, primary_key=True),
        sa.Column("due_at", TS, nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        _tenant(),
        sa.ForeignKeyConstraint(["item_id"], ["content_items.item_id"], ondelete="CASCADE"),
        sa.CheckConstraint("attempt >= 0", name="attempt_nonnegative"),
        sa.CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        sa.CheckConstraint("attempt <= max_attempts", name="attempt_within_max"),
    )
    op.create_index("ix_rechecks_due_at", "rechecks", ["due_at"])

    op.create_table(
        "audit_samples",
        sa.Column("sample_id", BIGPK, primary_key=True, autoincrement=True),
        sa.Column("item_id", BIGPK, nullable=False),
        sa.Column("decision_id", BIGPK, nullable=False),
        sa.Column("text_norm", sa.Text, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        _tenant(),
        _created_at(),
        sa.ForeignKeyConstraint(["item_id"], ["content_items.item_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decision_id"], ["decisions.decision_id"], ondelete="CASCADE"),
        sa.CheckConstraint("expires_at > created_at", name="expires_after_created"),
    )
    op.create_index("ix_audit_samples_expires_at", "audit_samples", ["expires_at"])

    op.create_table(
        "dead_letters",
        sa.Column("id", BIGPK, primary_key=True, autoincrement=True),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("envelope", JSONT, nullable=False),
        sa.Column("error", sa.Text, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        _tenant(),
        _created_at(),
        sa.CheckConstraint("expires_at > created_at", name="expires_after_created"),
    )
    op.create_index("ix_dead_letters_expires_at", "dead_letters", ["expires_at"])

    op.create_table(
        "budget_counters",
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("used", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("cap", sa.BigInteger),
        _tenant(),
        sa.PrimaryKeyConstraint("tenant_id", "day", "name"),
        sa.CheckConstraint("used >= 0", name="used_nonnegative"),
        sa.CheckConstraint("cap IS NULL OR cap >= 0", name="cap_nonnegative"),
    )

    op.create_table(
        "operator_tasks",
        sa.Column("task_id", BIGPK, primary_key=True, autoincrement=True),
        sa.Column("source_id", BIGPK),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("team", sa.String(64)),
        sa.Column("summary", sa.String(300), nullable=False),
        sa.Column("detail", JSONT, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("account_link", sa.Text),
        sa.Column("resolution", sa.Text),
        sa.Column("resolved_by", sa.String(128)),
        sa.Column("resolved_at", TS),
        _tenant(),
        _created_at(),
        sa.ForeignKeyConstraint(["source_id"], ["sources.source_id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "category IN ('flood_wait', 'access_denied', 'session_revoked', "
            "'challenge_required', 'account_banned', 'other')",
            name="category_valid",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'dismissed')", name="status_valid"
        ),
        sa.CheckConstraint(
            "account_link IS NULL OR substr(account_link, 1, 8) = 'https://'", name="link_is_https"
        ),
        sa.CheckConstraint(
            "status NOT IN ('resolved', 'dismissed') "
            "OR (resolved_at IS NOT NULL AND resolved_by IS NOT NULL)",
            name="closed_has_resolver",
        ),
    )
    op.create_index("ix_operator_tasks_status_priority", "operator_tasks", ["status", "priority"])
    op.create_index("ix_operator_tasks_source_id", "operator_tasks", ["source_id"])


def downgrade() -> None:
    op.drop_table("operator_tasks")
    op.drop_table("budget_counters")
    op.drop_table("dead_letters")
    op.drop_table("audit_samples")
    op.drop_table("rechecks")
    op.drop_table("decisions")
    op.drop_table("content_items")
