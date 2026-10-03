"""Modelo de dominio del perfil financiero, independiente de la API y la persistencia."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from app.finance.money import Money

Liquidity = Literal["high", "medium", "low"]
Priority = Literal["high", "medium", "low"]
CommitmentKind = Literal["monthly", "reserved_balance"]


@dataclass(frozen=True)
class Balance:
    """Saldo actual de un activo. Solo la liquidez alta cuenta como disponible."""

    name: str
    amount: Money
    liquidity: Liquidity
    category: str = "other"


@dataclass(frozen=True)
class MonthlyCashflow:
    """Flujo mensual en una moneda.

    `minimum_payments_included` indica si los pagos mínimos de deudas en esta moneda ya
    están dentro de `expenses`. None significa que la persona no lo declaró.
    """

    income: Money
    expenses: Money
    minimum_payments_included: bool | None = None

    def __post_init__(self) -> None:
        if self.income.currency != self.expenses.currency:
            raise ValueError("Income and expenses of one cashflow must share a currency.")
        if self.income.is_negative() or self.expenses.is_negative():
            raise ValueError("Income and expenses must be non-negative.")

    @property
    def currency(self) -> str:
        return self.income.currency


@dataclass(frozen=True)
class Commitment:
    """Compromiso fuera de los gastos declarados.

    `monthly` resta del flujo de cada mes; `reserved_balance` aparta saldo actual.
    """

    name: str
    amount: Money
    kind: CommitmentKind


@dataclass(frozen=True)
class Debt:
    name: str
    balance: Money
    apr_percent: Decimal | None = None
    minimum_payment: Money | None = None


@dataclass(frozen=True)
class Goal:
    name: str
    target: Money
    saved: Money
    priority: Priority = "medium"
    target_date: date | None = None
    horizon_months: int | None = None
    goal_id: str | None = None


@dataclass(frozen=True)
class FinancialSnapshot:
    as_of: date
    base_currency: str
    cashflows: tuple[MonthlyCashflow, ...]
    balances: tuple[Balance, ...] = ()
    debts: tuple[Debt, ...] = ()
    goals: tuple[Goal, ...] = ()
    commitments: tuple[Commitment, ...] = ()
    reserve_months: Decimal | None = None
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    missing_data: tuple[str, ...] = field(default_factory=tuple)

    def currencies(self) -> list[str]:
        found = {self.base_currency}
        found.update(c.currency for c in self.cashflows)
        found.update(b.amount.currency for b in self.balances)
        found.update(d.balance.currency for d in self.debts)
        found.update(g.target.currency for g in self.goals)
        found.update(c.amount.currency for c in self.commitments)
        return sorted(found, key=lambda c: (c != self.base_currency, c))
