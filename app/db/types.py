"""Tipo de columna para embeddings: `vector` de pgvector en PostgreSQL y JSON en SQLite."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.types import Text, TypeDecorator, UserDefinedType


class _PgVector(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_kw: Any) -> str:
        return "vector"


class EmbeddingType(TypeDecorator):
    """Guardo listas de floats. En PostgreSQL uso pgvector sin dimensión fija: cada modelo
    registra su dimensión en la fila y solo comparo vectores del mismo modelo."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PgVector())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return "[" + ",".join(f"{float(x):.7g}" for x in value) + "]"
        return json.dumps([float(x) for x in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            if dialect.name == "postgresql":
                return [float(x) for x in value.strip("[]").split(",") if x]
            return [float(x) for x in json.loads(value)]
        return [float(x) for x in value]
