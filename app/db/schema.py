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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db.types import EmbeddingType

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
    # Fecha desde la que el ahorro declarado ya incluye los aportes registrados.
    Column("saved_as_of", DateTime(timezone=True), nullable=False),
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
    Column("version", Integer, nullable=False),
    Column("status", String(12), nullable=False),
    Column("source", String(12), nullable=False),
    Column("source_scenario_id", String(36), nullable=True),
    Column("as_of", Date, nullable=False),
    Column("policy_version", String(40), nullable=False),
    Column("engine_version", String(40), nullable=False),
    Column("snapshot_schema_version", Integer, nullable=False),
    Column("inputs_fingerprint", String(64), nullable=False),
    Column("inputs", JsonType, nullable=False),
    Column("result", JsonType, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("superseded_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("status IN ('active', 'superseded')", name="status_valid"),
    CheckConstraint("source IN ('baseline', 'scenario', 'legacy')", name="source_valid"),
    CheckConstraint("version >= 1", name="version_positive"),
    UniqueConstraint("user_id", "version", name="uq_plans_user_id_version"),
    Index("ix_plans_user_id_created_at", "user_id", "created_at"),
    Index("ix_plans_created_at", "created_at"),
    Index(
        "uq_plans_one_active_per_user",
        "user_id",
        unique=True,
        postgresql_where=text("status = 'active'"),
        sqlite_where=text("status = 'active'"),
    ),
)

# Escenarios: simulaciones sobre el snapshot de un plan. Nunca modifican ese plan.
scenarios = Table(
    "scenarios",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("base_plan_id", String(36), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(80), nullable=False),
    Column("income_change", Numeric(6, 4), nullable=False),
    Column("expense_change", Numeric(6, 4), nullable=False),
    Column("annual_return", Numeric(6, 4), nullable=False),
    Column("status", String(12), nullable=False),
    Column("adopted_plan_id", String(36), nullable=True),
    Column("result", JsonType, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("adopted_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("status IN ('simulated', 'adopted')", name="status_valid"),
    CheckConstraint("income_change >= -1 AND income_change <= 5", name="income_change_range"),
    CheckConstraint("expense_change >= -1 AND expense_change <= 5", name="expense_change_range"),
    CheckConstraint("annual_return > -1 AND annual_return <= 1", name="annual_return_range"),
    Index("ix_scenarios_user_id_created_at", "user_id", "created_at"),
    Index("ix_scenarios_base_plan_id", "base_plan_id"),
)

# Avances registrados por meta y mes. `source` indica de dónde salió el dinero.
progress_entries = Table(
    "progress_entries",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("goal_id", String(36), ForeignKey("goals.id", ondelete="CASCADE"), nullable=False),
    Column("period", Date, nullable=False),
    Column("amount", Money, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("source", String(20), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("amount > 0", name="amount_positive"),
    CheckConstraint("source IN ('monthly_surplus', 'existing_balance')", name="source_valid"),
    CheckConstraint("length(currency) = 3", name="currency_iso"),
    Index("ix_progress_entries_user_id_period", "user_id", "period"),
    Index("ix_progress_entries_goal_id_recorded_at", "goal_id", "recorded_at"),
)

# Claves de idempotencia por cuenta: un reintento devuelve el recurso creado originalmente.
idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("key", String(128), primary_key=True),
    Column("operation", String(40), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("resource_type", String(20), nullable=False),
    Column("resource_id", String(36), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ix_idempotency_keys_created_at", "created_at"),
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
    # Procedencia y vigencia: solo recupero documentos aprobados y vigentes.
    Column("publisher", String(200), nullable=True),
    Column("published_on", Date, nullable=True),
    Column("reviewed_on", Date, nullable=True),
    Column("valid_until", Date, nullable=True),
    Column("review_status", String(12), nullable=False, server_default="pending"),
    CheckConstraint("corpus = 'public'", name="corpus_public_only"),
    CheckConstraint("review_status IN ('approved', 'pending', 'rejected')", name="review_status_valid"),
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
    # Fragmentos con instrucciones sospechosas: los guardo para auditoría, pero no los indexo ni recupero.
    Column("flagged_reason", String(40), nullable=True),
    CheckConstraint("corpus = 'public'", name="corpus_public_only"),
    UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_id_chunk_index"),
    Index("ix_chunks_corpus", "corpus"),
)

# Registro de índices vectoriales por modelo y dimensión de embeddings.
vector_indexes = Table(
    "vector_indexes",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("embedding_model", String(80), nullable=False),
    Column("dimension", Integer, nullable=False),
    Column("collection", String(120), nullable=False),
    Column("status", String(10), nullable=False),
    Column("chunk_count", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("status IN ('active', 'building', 'retired')", name="status_valid"),
    CheckConstraint("dimension > 0", name="dimension_positive"),
    UniqueConstraint("embedding_model", "dimension", name="uq_vector_indexes_embedding_model_dimension"),
)

# Explicaciones generadas de un plan. Guardo el resultado validado o la plantilla usada.
plan_explanations = Table(
    "plan_explanations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("plan_id", String(36), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
    Column("prompt_version", String(20), nullable=False),
    Column("provider", String(40), nullable=False),
    Column("model", String(80), nullable=False),
    Column("source", String(10), nullable=False),
    Column("fallback_reason", String(40), nullable=True),
    Column("content", JsonType, nullable=False),
    Column("input_tokens", Integer, nullable=False),
    Column("output_tokens", Integer, nullable=False),
    Column("latency_ms", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("source IN ('provider', 'template')", name="source_valid"),
    UniqueConstraint("plan_id", "prompt_version", "provider", "model", name="uq_plan_explanations_plan_id_prompt_version_provider_model"),
    Index("ix_plan_explanations_user_id_created_at", "user_id", "created_at"),
)

# Consumo diario por cuenta para aplicar cuota de generación.
explanation_usage = Table(
    "explanation_usage",
    metadata,
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("day", Date, primary_key=True),
    Column("calls", Integer, nullable=False),
    Column("tokens", Integer, nullable=False),
)

# Embeddings del corpus público, por modelo y dimensión. Viven en la base: un solo almacén y backup.
chunk_embeddings = Table(
    "chunk_embeddings",
    metadata,
    Column("chunk_id", String(36), ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True),
    Column("embedding_model", String(80), primary_key=True),
    Column("dimension", Integer, primary_key=True),
    Column("embedding", EmbeddingType(), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("dimension > 0", name="dimension_positive"),
    Index("ix_chunk_embeddings_embedding_model_dimension", "embedding_model", "dimension"),
)

# Estado de cada ingesta para reintentar sin duplicar ni dejar documentos a medias.
ingestion_jobs = Table(
    "ingestion_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("sha256", String(64), nullable=False),
    Column("document_id", String(36), nullable=True),
    Column("status", String(12), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("chunks_total", Integer, nullable=False),
    Column("chunks_embedded", Integer, nullable=False),
    Column("chunks_flagged", Integer, nullable=False),
    Column("error_code", String(40), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("sha256", name="uq_ingestion_jobs_sha256"),
    CheckConstraint("status IN ('pending', 'embedding', 'completed', 'failed')", name="status_valid"),
)

# Uso diario de la API por cuenta, para cuotas independientes de la cantidad de procesos.
api_usage = Table(
    "api_usage",
    metadata,
    Column("user_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("day", Date, primary_key=True),
    Column("requests", Integer, nullable=False),
)

PERSONAL_TABLES = ("api_usage", "explanation_usage", "plan_explanations", "idempotency_keys", "progress_entries", "scenarios", "plans", "goals", "profiles", "users")
