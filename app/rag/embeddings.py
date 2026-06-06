from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings


class Embeddings(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


_token_re = re.compile(r"[a-zA-Z0-9]{2,}")


@dataclass(frozen=True)
class HashEmbeddings:
    dimension: int = 768

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        tokens = _token_re.findall(text.lower())
        if not tokens:
            return vec
        for tok in tokens:
            digest = hashlib.md5(tok.encode("utf-8")).digest()
            raw = int.from_bytes(digest[:4], byteorder="big", signed=False)
            idx = raw % self.dimension
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


def build_embeddings(settings: Settings) -> tuple[Embeddings, str]:
    if settings.offline_mode or not settings.openai_api_key:
        return HashEmbeddings(), "offline"
    try:
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(api_key=settings.openai_api_key), "openai"
    except Exception:
        return HashEmbeddings(), "offline"
