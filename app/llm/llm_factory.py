from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


@dataclass(frozen=True)
class LlmBundle:
    llm: Any | None
    mode: str


def build_llm(settings: Settings) -> LlmBundle:
    if settings.offline_mode or not settings.openai_api_key:
        return LlmBundle(llm=None, mode="offline")
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(api_key=settings.openai_api_key, model=settings.openai_model, temperature=0.2)
        return LlmBundle(llm=llm, mode="llm")
    except Exception:
        return LlmBundle(llm=None, mode="offline")

