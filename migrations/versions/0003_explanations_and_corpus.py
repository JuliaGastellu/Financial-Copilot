"""Procedencia y vigencia del corpus, índices vectoriales versionados, explicaciones y cuota.

Los documentos existentes quedan como `pending` y sin vigencia: no se recuperan hasta que
alguien los vuelva a revisar e ingerir con procedencia.

Revision ID: 0003_explanations_and_corpus
Revises: 0002_plans_scenarios_progress
Create Date: 2026-10-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_explanations_and_corpus"
down_revision = "0002_plans_scenarios_progress"
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("publisher", sa.String(200), nullable=True))
        batch.add_column(sa.Column("published_on", sa.Date, nullable=True))
        batch.add_column(sa.Column("reviewed_on", sa.Date, nullable=True))
        batch.add_column(sa.Column("valid_until", sa.Date, nullable=True))
        batch.add_column(sa.Column("review_status", sa.String(12), nullable=False, server_default="pending"))
        batch.create_check_constraint("ck_documents_review_status_valid", "review_status IN ('approved', 'pending', 'rejected')")
    with op.batch_alter_table("chunks") as batch:
        batch.add_column(sa.Column("flagged_reason", sa.String(40), nullable=True))

    op.create_table(
        "vector_indexes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("embedding_model", sa.String(80), nullable=False),
        sa.Column("dimension", sa.Integer, nullable=False),
        sa.Column("collection", sa.String(120), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("chunk_count", sa.Integer, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_vector_indexes"),
        sa.CheckConstraint("status IN ('active', 'building', 'retired')", name="ck_vector_indexes_status_valid"),
        sa.CheckConstraint("dimension > 0", name="ck_vector_indexes_dimension_positive"),
        sa.UniqueConstraint("embedding_model", "dimension", name="uq_vector_indexes_embedding_model_dimension"),
    )
    op.create_table(
        "plan_explanations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("plan_id", sa.String(36), nullable=False),
        sa.Column("prompt_version", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(80), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("fallback_reason", sa.String(40), nullable=True),
        sa.Column("content", JSON_TYPE, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_plan_explanations"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_plan_explanations_user_id_users"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE", name="fk_plan_explanations_plan_id_plans"),
        sa.CheckConstraint("source IN ('provider', 'template')", name="ck_plan_explanations_source_valid"),
        sa.UniqueConstraint(
            "plan_id", "prompt_version", "provider", "model", name="uq_plan_explanations_plan_id_prompt_version_provider_model"
        ),
    )
    op.create_index("ix_plan_explanations_user_id_created_at", "plan_explanations", ["user_id", "created_at"])
    op.create_table(
        "explanation_usage",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("calls", sa.Integer, nullable=False),
        sa.Column("tokens", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "day", name="pk_explanation_usage"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_explanation_usage_user_id_users"),
    )


def downgrade() -> None:
    op.drop_table("explanation_usage")
    op.drop_index("ix_plan_explanations_user_id_created_at", table_name="plan_explanations")
    op.drop_table("plan_explanations")
    op.drop_table("vector_indexes")
    with op.batch_alter_table("chunks") as batch:
        batch.drop_column("flagged_reason")
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("ck_documents_review_status_valid", type_="check")
        for name in ("review_status", "valid_until", "reviewed_on", "published_on", "publisher"):
            batch.drop_column(name)
