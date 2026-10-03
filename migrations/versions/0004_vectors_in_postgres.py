"""Embeddings del corpus en la base relacional (pgvector) y estado de ingesta.

Reemplaza el índice Chroma local: los vectores quedan en el mismo almacén, backup y
transacción que los documentos. Los embeddings se regeneran con scripts/reindex_corpus.py.

Revision ID: 0004_vectors_in_postgres
Revises: 0003_explanations_and_corpus
Create Date: 2026-10-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import EmbeddingType

revision = "0004_vectors_in_postgres"
down_revision = "0003_explanations_and_corpus"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.String(36), nullable=False),
        sa.Column("embedding_model", sa.String(80), nullable=False),
        sa.Column("dimension", sa.Integer, nullable=False),
        sa.Column("embedding", EmbeddingType(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("chunk_id", "embedding_model", "dimension", name="pk_chunk_embeddings"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE", name="fk_chunk_embeddings_chunk_id_chunks"),
        sa.CheckConstraint("dimension > 0", name="ck_chunk_embeddings_dimension_positive"),
    )
    op.create_index("ix_chunk_embeddings_embedding_model_dimension", "chunk_embeddings", ["embedding_model", "dimension"])
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("chunks_total", sa.Integer, nullable=False),
        sa.Column("chunks_embedded", sa.Integer, nullable=False),
        sa.Column("chunks_flagged", sa.Integer, nullable=False),
        sa.Column("error_code", sa.String(40), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_jobs"),
        sa.UniqueConstraint("sha256", name="uq_ingestion_jobs_sha256"),
        sa.CheckConstraint("status IN ('pending', 'embedding', 'completed', 'failed')", name="ck_ingestion_jobs_status_valid"),
    )
    op.create_table(
        "api_usage",
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("requests", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "day", name="pk_api_usage"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name="fk_api_usage_user_id_users"),
    )


def downgrade() -> None:
    op.drop_table("api_usage")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_chunk_embeddings_embedding_model_dimension", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
