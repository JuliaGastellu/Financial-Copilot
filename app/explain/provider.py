"""Interfaz de proveedor de texto, desacoplada del resto del sistema.

El cálculo nunca depende de esta interfaz: si el proveedor está deshabilitado o falla, la
explicación usa la plantilla determinística.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings


class ProviderError(Exception):
    def __init__(self, code: str, transient: bool) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


@dataclass(frozen=True)
class ProviderResult:
    payload: object
    input_tokens: int
    output_tokens: int
    latency_ms: int


class TextProvider(Protocol):
    name: str
    model: str

    def generate(self, *, system: str, user: str, max_output_tokens: int, timeout_seconds: float) -> ProviderResult: ...


@dataclass(frozen=True)
class DisabledProvider:
    name: str = "disabled"
    model: str = "none"

    def generate(self, *, system: str, user: str, max_output_tokens: int, timeout_seconds: float) -> ProviderResult:
        raise ProviderError("provider_disabled", transient=False)


@dataclass(frozen=True)
class OpenAICompatibleProvider:
    """Proveedor con API de chat compatible con OpenAI. Pido salida JSON y temperatura 0."""

    api_key: str
    base_url: str
    model: str
    name: str = "openai_compatible"

    def generate(self, *, system: str, user: str, max_output_tokens: int, timeout_seconds: float) -> ProviderResult:
        import httpx

        started = time.monotonic()
        try:
            response = httpx.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0,
                    "max_tokens": max_output_tokens,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                },
                timeout=timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", transient=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("network_error", transient=True) from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise ProviderError(f"http_{response.status_code}", transient=True)
        if response.status_code >= 400:
            raise ProviderError(f"http_{response.status_code}", transient=False)
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
            payload = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("invalid_json", transient=False) from exc
        usage = data.get("usage") or {}
        return ProviderResult(
            payload=payload,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def build_provider(settings: Settings) -> TextProvider:
    if settings.offline_mode or settings.explanation_provider == "disabled" or not settings.openai_api_key:
        return DisabledProvider()
    return OpenAICompatibleProvider(
        api_key=settings.openai_api_key, base_url=settings.explanation_base_url, model=settings.explanation_model
    )
