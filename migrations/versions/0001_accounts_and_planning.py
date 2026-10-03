"""Cuentas, perfil, metas, planes, auditoría, recibos de borrado y corpus público.

Revision ID: 0001_accounts_and_planning
Revises:
Create Date: 2026-10-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_accounts_and_planning"
down_revision = None
branch_labels = None
depends_on = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
MONEY = sa.Numeric(20, 2)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
    )
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("data", JSON_TYPE, nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_profiles"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_profiles_user_id_users"),
        sa.CheckConstraint("length(base_currency) = 3", name="ck_profiles_base_currency_iso"),
    )
    op.create_table(
        "goals",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("target_amount", MONEY, nullable=False),
        sa.Column("saved_amount", MONEY, nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("target_date", sa.Date, nullable=True),
        sa.Column("horizon_months", sa.Integer, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_goals"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_goals_user_id_users"),
        sa.CheckConstraint("target_amount >= 0", name="ck_goals_target_non_negative"),
        sa.CheckConstraint("saved_amount >= 0", name="ck_goals_saved_non_negative"),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high')", name="ck_goals_priority_valid"),
        sa.CheckConstraint(
            "horizon_months IS NULL OR (horizon_months >= 1 AND horizon_months <= 600)", name="ck_goals_horizon_range"
        ),
        sa.CheckConstraint("length(currency) = 3", name="ck_goals_currency_iso"),
    )
    op.create_index("ix_goals_user_id_created_at", "goals", ["user_id", "created_at"])
    op.create_table(
        "plans",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("policy_version", sa.String(40), nullable=False),
        sa.Column("inputs", JSON_TYPE, nullable=False),
        sa.Column("result", JSON_TYPE, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_plans"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_plans_user_id_users"),
    )
    op.create_index("ix_plans_user_id_created_at", "plans", ["user_id", "created_at"])
    op.create_index("ix_plans_created_at", "plans", ["created_at"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.CheckConstraint("outcome IN ('success', 'denied', 'not_found', 'error')", name="ck_audit_events_outcome_valid"),
    )
    op.create_index("ix_audit_events_user_id_occurred_at", "audit_events", ["user_id", "occurred_at"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_table(
        "deletion_receipts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("deleted_at", TS, nullable=False),
        sa.Column("evidence", JSON_TYPE, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_deletion_receipts"),
    )
    op.create_index("ix_deletion_receipts_subject_hash", "deletion_receipts", ["subject_hash"])
    op.create_index("ix_deletion_receipts_deleted_at", "deletion_receipts", ["deleted_at"])
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("corpus", sa.String(16), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("source", sa.String(1000), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.CheckConstraint("corpus = 'public'", name="ck_documents_corpus_public_only"),
        sa.UniqueConstraint("corpus", "sha256", name="uq_documents_corpus_sha256"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("corpus", sa.String(16), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE", name="fk_chunks_document_id_documents"),
        sa.CheckConstraint("corpus = 'public'", name="ck_chunks_corpus_public_only"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_id_chunk_index"),
    )
    op.create_index("ix_chunks_corpus", "chunks", ["corpus"])


def downgrade() -> None:
    op.drop_index("ix_chunks_corpus", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_index("ix_deletion_receipts_deleted_at", table_name="deletion_receipts")
    op.drop_index("ix_deletion_receipts_subject_hash", table_name="deletion_receipts")
    op.drop_table("deletion_receipts")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_user_id_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_plans_created_at", table_name="plans")
    op.drop_index("ix_plans_user_id_created_at", table_name="plans")
    op.drop_table("plans")
    op.drop_index("ix_goals_user_id_created_at", table_name="goals")
    op.drop_table("goals")
    op.drop_table("profiles")
    op.drop_table("users")
