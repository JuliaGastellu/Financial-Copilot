"""Políticas explícitas del plan. Cada umbral corresponde a una única métrica con su unidad."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PlanningPolicy:
    version: str = "2026-10-03.1"

    # Meses de salidas mensuales que reservo cuando la persona no eligió otro valor.
    default_reserve_months: Decimal = Decimal("3")
    max_reserve_months: Decimal = Decimal("24")

    # Tasa anual nominal en porcentaje (0-100) desde la que considero cara una deuda.
    high_apr_threshold_percent: Decimal = Decimal("12")

    # debt_service_ratio = pagos mínimos mensuales / ingreso mensual (fracción).
    debt_service_medium: Decimal = Decimal("0.20")
    debt_service_high: Decimal = Decimal("0.35")

    # debt_to_assets_ratio = saldo de deudas / valor total de activos (fracción).
    debt_to_assets_medium: Decimal = Decimal("0.6")
    debt_to_assets_high: Decimal = Decimal("1.0")

    # savings_rate = excedente mensual / ingreso mensual (fracción).
    low_savings_rate: Decimal = Decimal("0.10")

    max_scenarios: int = 3


DEFAULT_POLICY = PlanningPolicy()
