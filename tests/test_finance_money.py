from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.finance.money import (
    CurrencyMismatchError,
    ExchangeRate,
    ExchangeRateError,
    InvalidAmountError,
    Money,
    consolidate,
    convert,
    to_decimal,
)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity", True, None, [1]])
def test_non_finite_or_invalid_amounts_are_rejected(value: object) -> None:
    with pytest.raises((InvalidAmountError, TypeError)):
        Money.of(value, "USD")


def test_float_input_does_not_carry_binary_error() -> None:
    assert to_decimal(0.1) + to_decimal(0.2) == Decimal("0.3")


def test_currency_code_is_validated_and_normalized() -> None:
    assert Money.of(1, "usd").currency == "USD"
    with pytest.raises(ValueError):
        Money.of(1, "US")
    with pytest.raises(ValueError):
        Money.of(1, "U$D")


def test_operations_between_currencies_are_rejected() -> None:
    usd = Money.of(10, "USD")
    ars = Money.of(10, "ARS")
    with pytest.raises(CurrencyMismatchError):
        usd + ars
    with pytest.raises(CurrencyMismatchError):
        usd - ars
    with pytest.raises(CurrencyMismatchError):
        _ = usd < ars


def test_rounding_uses_minor_units() -> None:
    assert Money.of("10.005", "USD").round().amount == Decimal("10.00")  # mitad al par
    assert Money.of("10.015", "USD").round().amount == Decimal("10.02")
    assert Money.of("10.001", "USD").round_up().amount == Decimal("10.01")
    assert Money.of("10.009", "USD").round_down().amount == Decimal("10.00")
    assert Money.of("1500.6", "JPY").round().amount == Decimal("1501")
    assert Money.of("2.5", "USD").to_json() == {"amount": "2.50", "currency": "USD"}


def test_conversion_requires_matching_fresh_rate_with_source() -> None:
    rate = ExchangeRate("USD", "ARS", Decimal("1000"), date(2026, 10, 1), "fixture")
    on = date(2026, 10, 3)
    assert convert(Money.of(2, "USD"), rate, on=on, max_age_days=5) == Money.of(2000, "ARS")
    with pytest.raises(ExchangeRateError):
        convert(Money.of(2, "EUR"), rate, on=on, max_age_days=5)
    with pytest.raises(ExchangeRateError):
        convert(Money.of(2, "USD"), rate, on=on, max_age_days=1)
    with pytest.raises(ExchangeRateError):
        convert(Money.of(2, "USD"), rate, on=date(2026, 9, 30), max_age_days=5)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"rate": Decimal("0")},
        {"rate": Decimal("-1")},
        {"source": " "},
        {"quote": "USD"},
    ],
)
def test_invalid_exchange_rates_are_rejected(kwargs: dict) -> None:
    params = {"base": "USD", "quote": "ARS", "rate": Decimal("1000"), "as_of": date(2026, 10, 1), "source": "fixture"}
    params.update(kwargs)
    with pytest.raises(ExchangeRateError):
        ExchangeRate(**params)


def test_consolidation_fails_without_rate_and_works_with_explicit_rate() -> None:
    amounts = [Money.of(100, "USD"), Money.of(50000, "ARS")]
    on = date(2026, 10, 3)
    with pytest.raises(ExchangeRateError):
        consolidate(amounts, target_currency="USD", rates=[], on=on, max_age_days=3)
    rate = ExchangeRate("ARS", "USD", Decimal("0.001"), date(2026, 10, 2), "fixture")
    assert consolidate(amounts, target_currency="USD", rates=[rate], on=on, max_age_days=3) == Money.of(150, "USD")
