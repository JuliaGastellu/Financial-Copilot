"""Embeddings con identidad explícita (modelo y dimensión) para versionar índices."""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings


class Embeddings(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class EmbeddingSpec:
    """Identidad de un espacio vectorial: vectores de modelos o dimensiones distintas no se mezclan."""

    model: str
    dimension: int
    mode: str

    @property
    def collection(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.model.lower()).strip("-")
        return f"public-corpus-{slug}-{self.dimension}"


# Palabras muy frecuentes que no aportan al parecido entre textos.
_STOPWORDS = frozenset(
    """a al algo como con cual cuando de del desde donde e el ella ellos en entre es esa ese eso esta este esto
    fue ha hay la las le les lo los mas me mi muy no nos o para pero por que se si sin sobre son su sus te tu
    un una uno unos y ya the of and to in is for on that with as are be it this""".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def normalize_tokens(text: str) -> list[str]:
    """Paso a minúsculas, quito tildes y descarto palabras vacías."""
    folded = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(c for c in folded if not unicodedata.combining(c))
    return [_singular(t) for t in _TOKEN_RE.findall(ascii_text) if t not in _STOPWORDS]


def _singular(token: str) -> str:
    """Quito el plural simple para que «mínimos» y «mínimo» coincidan; no es un lematizador."""
    if len(token) > 4 and token.endswith("es") and token[-3] not in "aeiou":
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


@dataclass(frozen=True)
class HashEmbeddings:
    """Representación local sin red: bolsa de palabras con hash. No captura sinónimos."""

    dimension: int = 768
    version: str = "hash-v2"

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for tok in normalize_tokens(text):
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            vec[int.from_bytes(digest[:4], "big") % self.dimension] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return vec if norm == 0 else [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


def build_embeddings(settings: Settings) -> tuple[Embeddings, EmbeddingSpec]:
    if settings.offline_mode or not settings.openai_api_key:
        hashed = HashEmbeddings()
        return hashed, EmbeddingSpec(hashed.version, hashed.dimension, "offline")
    from langchain_openai import OpenAIEmbeddings

    embeddings = OpenAIEmbeddings(api_key=settings.openai_api_key, model=settings.embedding_model, dimensions=settings.embedding_dimension)
    return embeddings, EmbeddingSpec(settings.embedding_model, settings.embedding_dimension, "provider")
