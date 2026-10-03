"""Explicación de planes calculados. El proveedor redacta; el plan decide.

Orden de controles: plan propio y reproducible → caché → cuota → proveedor habilitado →
límite de entrada → generación con timeout y reintentos acotados → validación contra los
hechos → nombres reales restituidos en el servidor. Cualquier fallo usa la plantilla.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.observability import log_event
from app.data.accounts import UserRecord, new_id, utc_now
from app.db.schema import explanation_usage, plan_explanations
from app.explain.facts import PlanFacts, build_facts
from app.explain.provider import ProviderError, TextProvider
from app.explain.template import build_template, render
from app.explain.validation import ExplanationOutput, ExplanationRejected, validate_output
from app.schemas.plans_v1 import PlanResultV1

PROMPT_VERSION = "explain-v1"

SYSTEM_PROMPT = """Explicás en castellano rioplatense, con frases claras, un plan financiero que ya está calculado.
Reglas obligatorias:
- Usá solo los hechos del JSON. No calcules, no redondees y no inventes cifras: copiá los importes tal como aparecen, con su código de moneda (por ejemplo, ARS 550000.00).
- No agregues recomendaciones nuevas, productos, inversiones, préstamos, probabilidades, porcentajes ni garantías.
- No cambies prioridades, estados ni restricciones. Si mencionás la prioridad de una meta, usá la del JSON.
- Referite a las metas solo por su etiqueta (meta-1, meta-2). No escribas fechas.
- Cada punto tiene que listar en "facts" los identificadores de los hechos que usa.
Respondé solo con JSON: {"summary": {"text": "...", "facts": ["f1"]}, "points": [{"text": "...", "facts": ["f2"]}]}.
Máximo 5 puntos y 300 caracteres por texto."""


@dataclass(frozen=True)
class Explanation:
    source: Literal["provider", "template"]
    fallback_reason: str | None
    output: ExplanationOutput
    provider: str
    model: str
    prompt_version: str
    created_at: datetime
    cached: bool


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class ExplanationService:
    engine: Engine
    settings: Settings
    provider: TextProvider

    def _cached(self, plan_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(plan_explanations).where(
                    plan_explanations.c.plan_id == plan_id,
                    plan_explanations.c.prompt_version == PROMPT_VERSION,
                    plan_explanations.c.provider == self.provider.name,
                    plan_explanations.c.model == self.provider.model,
                )
            ).mappings().first()
            return dict(row) if row else None

    def _usage_today(self, user_id: str) -> tuple[int, int]:
        today = datetime.now(tz=UTC).date()
        with self.engine.connect() as conn:
            row = conn.execute(
                select(explanation_usage.c.calls, explanation_usage.c.tokens).where(
                    explanation_usage.c.user_id == user_id, explanation_usage.c.day == today
                )
            ).first()
        return (row.calls, row.tokens) if row else (0, 0)

    def _record_usage(self, user_id: str, tokens: int) -> None:
        today = datetime.now(tz=UTC).date()
        with self.engine.begin() as conn:
            result = conn.execute(
                update(explanation_usage)
                .where(explanation_usage.c.user_id == user_id, explanation_usage.c.day == today)
                .values(calls=explanation_usage.c.calls + 1, tokens=explanation_usage.c.tokens + tokens)
            )
            if result.rowcount == 0:
                conn.execute(insert(explanation_usage).values(user_id=user_id, day=today, calls=1, tokens=tokens))

    def _generate(self, pf: PlanFacts) -> tuple[ExplanationOutput | None, str | None, int, int, int]:
        """Devuelvo (salida validada, motivo de respaldo, tokens de entrada, de salida, latencia)."""
        user_message = json.dumps(pf.for_provider(), ensure_ascii=False, separators=(",", ":"))
        if _estimate_tokens(SYSTEM_PROMPT + user_message) > self.settings.explanation_max_input_tokens:
            return None, "input_too_large", 0, 0, 0
        attempts = 1 + self.settings.explanation_max_retries
        last_error = "provider_error"
        input_tokens = output_tokens = latency = 0
        for attempt in range(attempts):
            try:
                result = self.provider.generate(
                    system=SYSTEM_PROMPT,
                    user=user_message,
                    max_output_tokens=self.settings.explanation_max_output_tokens,
                    timeout_seconds=self.settings.explanation_timeout_seconds,
                )
            except ProviderError as exc:
                last_error = exc.code
                if exc.transient and attempt + 1 < attempts:
                    time.sleep(min(2.0, 0.25 * (2**attempt)))
                    continue
                return None, last_error, input_tokens, output_tokens, latency
            input_tokens += result.input_tokens
            output_tokens += result.output_tokens
            latency += result.latency_ms
            if result.output_tokens > self.settings.explanation_max_output_tokens:
                return None, "output_too_large", input_tokens, output_tokens, latency
            try:
                return validate_output(pf, result.payload), None, input_tokens, output_tokens, latency
            except ExplanationRejected as exc:
                # Una salida que contradice el plan no se reintenta: uso la plantilla.
                return None, f"rejected:{exc.code}", input_tokens, output_tokens, latency
        return None, last_error, input_tokens, output_tokens, latency

    def explain(self, user: UserRecord, plan_id: str, result: PlanResultV1, request_id: str | None = None) -> Explanation:
        cached = self._cached(plan_id)
        if cached is not None:
            return Explanation(
                source=cached["source"],
                fallback_reason=cached["fallback_reason"],
                output=ExplanationOutput.model_validate(cached["content"]),
                provider=cached["provider"],
                model=cached["model"],
                prompt_version=cached["prompt_version"],
                created_at=cached["created_at"],
                cached=True,
            )
        pf = build_facts(result)
        calls, tokens = self._usage_today(user.id)
        started = time.monotonic()
        output: ExplanationOutput | None = None
        reason: str | None
        input_tokens = output_tokens = latency = 0
        if self.provider.name == "disabled":
            reason = "provider_disabled"
        elif calls >= self.settings.explanation_daily_quota or tokens >= self.settings.explanation_daily_token_budget:
            reason = "quota_exceeded"
        else:
            output, reason, input_tokens, output_tokens, latency = self._generate(pf)
            self._record_usage(user.id, input_tokens + output_tokens)
        source: Literal["provider", "template"] = "provider" if output is not None else "template"
        final = render(output if output is not None else build_template(pf), pf)
        latency = latency or int((time.monotonic() - started) * 1000)
        now = utc_now()
        # No guardo en caché los respaldos por cuota o fallos transitorios: un reintento posterior puede mejorar.
        persist = source == "provider" or reason in ("provider_disabled",) or (reason or "").startswith("rejected:")
        if persist:
            try:
                with self.engine.begin() as conn:
                    conn.execute(
                        insert(plan_explanations).values(
                            id=new_id(),
                            user_id=user.id,
                            plan_id=plan_id,
                            prompt_version=PROMPT_VERSION,
                            provider=self.provider.name,
                            model=self.provider.model,
                            source=source,
                            fallback_reason=reason,
                            content=final.model_dump(mode="json"),
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            latency_ms=latency,
                            created_at=now,
                        )
                    )
            except IntegrityError:
                pass
        log_event(
            "plan_explained",
            request_id=request_id,
            user_id=user.id,
            source=source,
            fallback_reason=reason,
            provider=self.provider.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency,
        )
        return Explanation(source, reason, final, self.provider.name, self.provider.model, PROMPT_VERSION, now, cached=False)
