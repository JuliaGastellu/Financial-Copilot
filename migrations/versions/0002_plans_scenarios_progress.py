"""Versiones de plan, escenarios, avances e idempotencia.

Los planes existentes pasan a ser versiones `legacy` no reproducibles: conservo su resultado,
marco como vigente el más reciente de cada cuenta y el resto como reemplazado.

Revision ID: 0002_plans_scenarios_progress
Revises: 0001_accounts_and_planning
Create Date: 2026-10-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_plans_scenarios_progress"
down_revision = "0001_accounts_and_planning"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
MONEY = sa.Numeric(20, 2)
TS = sa.DateTime(timezone=True)
ACTIVE = sa.text("status = 'active'")


def upgrade() -> None:
    with op.batch_alter_table("goals") as batch:
        batch.add_column(sa.Column("saved_as_of", TS, nullable=True))
    op.execute("UPDATE goals SET saved_as_of = updated_at")
    with op.batch_alter_table("goals") as batch:
        batch.alter_column("saved_as_of", existing_type=TS, nullable=False)

    with op.batch_alter_table("plans") as batch:
        batch.add_column(sa.Column("version", sa.Integer, nullable=True))
        batch.add_column(sa.Column("status", sa.String(12), nullable=True))
        batch.add_column(sa.Column("source", sa.String(12), nullable=True))
        batch.add_column(sa.Column("source_scenario_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("engine_version", sa.String(40), nullable=True))
        batch.add_column(sa.Column("snapshot_schema_version", sa.Integer, nullable=True))
        batch.add_column(sa.Column("inputs_fingerprint", sa.String(64), nullable=True))
        batch.add_column(sa.Column("superseded_at", TS, nullable=True))
    op.execute(
        """
        UPDATE plans SET version = (
            SELECT COUNT(*) FROM plans AS p2
            WHERE p2.user_id = plans.user_id
              AND (p2.created_at < plans.created_at OR (p2.created_at = plans.created_at AND p2.id <= plans.id))
        )
        """
    )
    op.execute(
        """
        UPDATE plans SET status = CASE WHEN version = (
            SELECT MAX(p2.version) FROM plans AS p2 WHERE p2.user_id = plans.user_id
        ) THEN 'active' ELSE 'superseded' END
        """
    )
    op.execute(
        "UPDATE plans SET source = 'legacy', engine_version = 'legacy', snapshot_schema_version = 0, inputs_fingerprint = ''"
    )
    with op.batch_alter_table("plans") as batch:
        for name, type_ in (
            ("version", sa.Integer()),
            ("status", sa.String(12)),
            ("source", sa.String(12)),
            ("engine_version", sa.String(40)),
            ("snapshot_schema_version", sa.Integer()),
            ("inputs_fingerprint", sa.String(64)),
        ):
            batch.alter_column(name, existing_type=type_, nullable=False)
        batch.create_check_constraint("ck_plans_status_valid", "status IN ('active', 'superseded')")
        batch.create_check_constraint("ck_plans_source_valid", "source IN ('baseline', 'scenario', 'legacy')")
        batch.create_check_constraint("ck_plans_version_positive", "version >= 1")
        batch.create_unique_constraint("uq_plans_user_id_version", ["user_id", "version"])
    op.create_index(
        "uq_plans_one_active_per_user", "plans", ["user_id"], unique=True, postgresql_where=ACTIVE, sqlite_where=ACTIVE
    )

    op.create_table(
        "scenarios",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("base_plan_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("income_change", sa.Numeric(6, 4), nullable=False),
        sa.Column("expense_change", sa.Numeric(6, 4), nullable=False),
        sa.Column("annual_return", sa.Numeric(6, 4), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("adopted_plan_id", sa.String(36), nullable=True),
        sa.Column("result", JSON_TYPE, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("adopted_at", TS, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_scenarios"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_scenarios_user_id_users"),
        sa.ForeignKeyConstraint(["base_plan_id"], ["plans.id"], ondelete="CASCADE", name="fk_scenarios_base_plan_id_plans"),
        sa.CheckConstraint("status IN ('simulated', 'adopted')", name="ck_scenarios_status_valid"),
        sa.CheckConstraint("income_change >= -1 AND income_change <= 5", name="ck_scenarios_income_change_range"),
        sa.CheckConstraint("expense_change >= -1 AND expense_change <= 5", name="ck_scenarios_expense_change_range"),
        sa.CheckConstraint("annual_return > -1 AND annual_return <= 1", name="ck_scenarios_annual_return_range"),
    )
    op.create_index("ix_scenarios_user_id_created_at", "scenarios", ["user_id", "created_at"])
    op.create_index("ix_scenarios_base_plan_id", "scenarios", ["base_plan_id"])

    op.create_table(
        "progress_entries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("period", sa.Date, nullable=False),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("recorded_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_progress_entries"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_progress_entries_user_id_users"),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE", name="fk_progress_entries_goal_id_goals"),
        sa.CheckConstraint("amount > 0", name="ck_progress_entries_amount_positive"),
        sa.CheckConstraint("source IN ('monthly_surplus', 'existing_balance')", name="ck_progress_entries_source_valid"),
        sa.CheckConstraint("length(currency) = 3", name="ck_progress_entries_currency_iso"),
    )
    op.create_index("ix_progress_entries_user_id_period", "progress_entries", ["user_id", "period"])
    op.create_index("ix_progress_entries_goal_id_recorded_at", "progress_entries", ["goal_id", "recorded_at"])

    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(20), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "key", name="pk_idempotency_keys"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_idempotency_keys_user_id_users"),
    )
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_created_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_index("ix_progress_entries_goal_id_recorded_at", table_name="progress_entries")
    op.drop_index("ix_progress_entries_user_id_period", table_name="progress_entries")
    op.drop_table("progress_entries")
    op.drop_index("ix_scenarios_base_plan_id", table_name="scenarios")
    op.drop_index("ix_scenarios_user_id_created_at", table_name="scenarios")
    op.drop_table("scenarios")
    op.drop_index("uq_plans_one_active_per_user", table_name="plans")
    with op.batch_alter_table("plans") as batch:
        batch.drop_constraint("uq_plans_user_id_version", type_="unique")
        batch.drop_constraint("ck_plans_version_positive", type_="check")
        batch.drop_constraint("ck_plans_source_valid", type_="check")
        batch.drop_constraint("ck_plans_status_valid", type_="check")
        for name in (
            "superseded_at",
            "inputs_fingerprint",
            "snapshot_schema_version",
            "engine_version",
            "source_scenario_id",
            "source",
            "status",
            "version",
        ):
            batch.drop_column(name)
    with op.batch_alter_table("goals") as batch:
        batch.drop_column("saved_as_of")
