"""Importes con Decimal y moneda explícita.

No convierto monedas de forma implícita: toda operación entre importes exige la
misma moneda. Una conversión necesita una tasa con fecha y fuente verificables.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal, InvalidOperation
from typing import Any, Iterable

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

# Uso dos decimales salvo en monedas sin unidad menor de uso habitual.
_ZERO_DECIMAL_CURRENCIES = frozenset({"CLP", "ISK", "JPY", "KRW", "PYG", "UGX", "VND"})


class InvalidAmountError(ValueError):
    """El valor no es un número finito representable como Decimal."""


class CurrencyMismatchError(ValueError):
    """Intenté operar importes de monedas distintas sin conversión explícita."""


class ExchangeRateError(ValueError):
    """La tasa no corresponde al par pedido, está vencida o es posterior a la fecha."""


def to_decimal(value: Any) -> Decimal:
    """Convierto a Decimal rechazando booleanos, NaN e infinitos.

    Paso los float por su representación textual para no arrastrar el error binario.
    """
    if isinstance(value, bool):
        raise InvalidAmountError("Boolean values are not amounts.")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, float):
        result = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except InvalidOperation as exc:
            raise InvalidAmountError(f"Invalid amount: {value!r}") from exc
    else:
        raise InvalidAmountError(f"Unsupported amount type: {type(value).__name__}")
    if not result.is_finite():
        raise InvalidAmountError("Amounts must be finite.")
    return result


def normalize_currency(code: Any) -> str:
    if not isinstance(code, str):
        raise ValueError("Currency must be an ISO 4217 code.")
    normalized = code.strip().upper()
    if not _CURRENCY_RE.match(normalized):
        raise ValueError(f"Invalid ISO 4217 currency code: {code!r}")
    return normalized


def minor_unit(currency: str) -> Decimal:
    return Decimal("1") if currency in _ZERO_DECIMAL_CURRENCIES else Decimal("0.01")


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", to_decimal(self.amount))
        object.__setattr__(self, "currency", normalize_currency(self.currency))

    @classmethod
    def of(cls, amount: Any, currency: str) -> Money:
        return cls(to_decimal(amount), currency)

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(Decimal("0"), currency)

    def _check(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError("Money can only be combined with Money.")
        if other.currency != self.currency:
            raise CurrencyMismatchError(f"Cannot combine {self.currency} with {other.currency} without an explicit exchange rate.")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __lt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount < other.amount

    def __le__(self, other: Money) -> bool:
        self._check(other)
        return self.amount <= other.amount

    def __gt__(self, other: Money) -> bool:
        self._check(other)
        return self.amount > other.amount

    def __ge__(self, other: Money) -> bool:
        self._check(other)
        return self.amount >= other.amount

    def times(self, factor: Any) -> Money:
        return Money(self.amount * to_decimal(factor), self.currency)

    def is_zero(self) -> bool:
        return self.amount == 0

    def is_positive(self) -> bool:
        return self.amount > 0

    def is_negative(self) -> bool:
        return self.amount < 0

    def clamp_non_negative(self) -> Money:
        return self if self.amount >= 0 else Money.zero(self.currency)

    def round(self, rounding: str = ROUND_HALF_EVEN) -> Money:
        return Money(self.amount.quantize(minor_unit(self.currency), rounding=rounding), self.currency)

    def round_down(self) -> Money:
        """Redondeo hacia cero; lo uso para asignaciones que no pueden exceder el presupuesto."""
        return self.round(ROUND_DOWN)

    def round_up(self) -> Money:
        """Redondeo alejándome de cero; lo uso para aportes requeridos."""
        return self.round(ROUND_UP)

    def to_json(self) -> dict[str, str]:
        return {"amount": format(self.round().amount, "f"), "currency": self.currency}


def money_min(a: Money, b: Money) -> Money:
    return a if a <= b else b


def money_max(a: Money, b: Money) -> Money:
    return a if a >= b else b


def money_sum(items: Iterable[Money], currency: str) -> Money:
    total = Money.zero(currency)
    for item in items:
        total = total + item
    return total


@dataclass(frozen=True)
class ExchangeRate:
    """Una unidad de `base` equivale a `rate` unidades de `quote` en `as_of`, según `source`."""

    base: str
    quote: str
    rate: Decimal
    as_of: date
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", normalize_currency(self.base))
        object.__setattr__(self, "quote", normalize_currency(self.quote))
        rate = to_decimal(self.rate)
        if rate <= 0:
            raise ExchangeRateError("Exchange rate must be positive.")
        object.__setattr__(self, "rate", rate)
        if self.base == self.quote:
            raise ExchangeRateError("Exchange rate needs two different currencies.")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ExchangeRateError("Exchange rate needs a source.")


def convert(money: Money, rate: ExchangeRate, *, on: date, max_age_days: int) -> Money:
    """Convierto solo con una tasa explícita del par exacto, no futura y vigente."""
    if money.currency != rate.base:
        raise ExchangeRateError(f"Rate {rate.base}/{rate.quote} cannot convert {money.currency}.")
    if rate.as_of > on:
        raise ExchangeRateError("Exchange rate date is after the conversion date.")
    if (on - rate.as_of).days > max_age_days:
        raise ExchangeRateError("Exchange rate is stale.")
    return Money(money.amount * rate.rate, rate.quote).round()


def consolidate(
    amounts: Iterable[Money],
    *,
    target_currency: str,
    rates: Iterable[ExchangeRate],
    on: date,
    max_age_days: int,
) -> Money:
    """Sumo importes en una moneda destino; falla si falta o venció alguna tasa."""
    target = normalize_currency(target_currency)
    by_pair = {(r.base, r.quote): r for r in rates}
    total = Money.zero(target)
    for item in amounts:
        if item.currency == target:
            total = total + item
            continue
        rate = by_pair.get((item.currency, target))
        if rate is None:
            raise ExchangeRateError(f"Missing exchange rate {item.currency}/{target}.")
        total = total + convert(item, rate, on=on, max_age_days=max_age_days)
    return total
