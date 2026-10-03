"""Esquema relacional. Las migraciones de `migrations/versions/` son la fuente para crear tablas;
uso estas definiciones para construir consultas y para verificar que coincidan con la migración.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

JsonType = JSON().with_variant(JSONB(), "postgresql")
Money = Numeric(20, 2)

users = Table(
    "users",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("issuer", String(512), nullable=False),
    Column("subject", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
)

profiles = Table(
    "profiles",
    metadata,
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("base_currency", String(3), nullable=False),
    Column("data", JsonType, nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("length(base_currency) = 3", name="base_currency_iso"),
)

goals = Table(
    "goals",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(120), nullable=False),
    Column("currency", String(3), nullable=False),
    Column("target_amount", Money, nullable=False),
    Column("saved_amount", Money, nullable=False),
    Column("priority", String(10), nullable=False),
    Column("target_date", Date, nullable=True),
    Column("horizon_months", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("target_amount >= 0", name="target_non_negative"),
    CheckConstraint("saved_amount >= 0", name="saved_non_negative"),
    CheckConstraint("priority IN ('low', 'medium', 'high')", name="priority_valid"),
    CheckConstraint("horizon_months IS NULL OR (horizon_months >= 1 AND horizon_months <= 600)", name="horizon_range"),
    CheckConstraint("length(currency) = 3", name="currency_iso"),
    Index("ix_goals_user_id_created_at", "user_id", "created_at"),
)

plans = Table(
    "plans",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("as_of", Date, nullable=False),
    Column("policy_version", String(40), nullable=False),
    Column("inputs", JsonType, nullable=False),
    Column("result", JsonType, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_plans_user_id_created_at", "user_id", "created_at"),
    Index("ix_plans_created_at", "created_at"),
)

# Auditoría mínima: nunca guardo importes, nombres de metas ni texto financiero.
audit_events = Table(
    "audit_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("user_id", String(36), nullable=True),
    Column("action", String(64), nullable=False),
    Column("resource_type", String(32), nullable=False),
    Column("resource_id", String(36), nullable=True),
    Column("outcome", String(16), nullable=False),
    Column("request_id", String(64), nullable=True),
    CheckConstraint("outcome IN ('success', 'denied', 'not_found', 'error')", name="outcome_valid"),
    Index("ix_audit_events_user_id_occurred_at", "user_id", "occurred_at"),
    Index("ix_audit_events_occurred_at", "occurred_at"),
)

# Recibo de borrado: identidad seudonimizada con HMAC y conteos por almacén, sin contenido.
deletion_receipts = Table(
    "deletion_receipts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("subject_hash", String(64), nullable=False),
    Column("deleted_at", DateTime(timezone=True), nullable=False),
    Column("evidence", JsonType, nullable=False),
    Index("ix_deletion_receipts_subject_hash", "subject_hash"),
    Index("ix_deletion_receipts_deleted_at", "deleted_at"),
)

# Corpus público curado. No existe columna de propietario: los documentos privados están fuera de esta etapa.
documents = Table(
    "documents",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("corpus", String(16), nullable=False),
    Column("title", String(300), nullable=False),
    Column("source", String(1000), nullable=True),
    Column("content", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("corpus = 'public'", name="corpus_public_only"),
    UniqueConstraint("corpus", "sha256", name="uq_documents_corpus_sha256"),
)

chunks = Table(
    "chunks",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("document_id", String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
    Column("corpus", String(16), nullable=False),
    Column("chunk_index", Integer, nullable=False),
    Column("content", Text, nullable=False),
    Column("sha256", String(64), nullable=False),
    CheckConstraint("corpus = 'public'", name="corpus_public_only"),
    UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_id_chunk_index"),
    Index("ix_chunks_corpus", "corpus"),
)

PERSONAL_TABLES = ("plans", "goals", "profiles", "users")
