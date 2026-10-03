"""Invariantes del plan financiero y casos límite.

Uso una fecha fija para que cada plan sea reproducible.
"""
from __future__ import annotations

import itertools
import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.finance import plan_for_profile
from app.finance.adapters import snapshot_from_profile
from app.finance.money import Money
from app.finance.planning import (
    FinancialPlan,
    Scenario,
    build_plan,
    months_to_reach,
    project_balance,
    run_scenarios,
    whole_months_between,
)
from app.finance.serialization import plan_metrics, plan_to_dict

AS_OF = date(2026, 10, 3)


def _profile(**overrides: Any) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "user_id": "u",
        "currency": "USD",
        "risk_tolerance": "medium",
        "cashflow": {"monthly_income": 7000, "monthly_expenses": 4500},
        "assets": [{"name": "Cash", "category": "cash", "value": 8000, "liquidity": "high"}],
        "liabilities": [],
        "goals": [
            {"name": "Down payment", "target_amount": 20000, "horizon_months": 18, "priority": "high"},
            {"name": "Car", "target_amount": 9000, "horizon_months": 12, "priority": "medium"},
            {"name": "Trip", "target_amount": 3000, "horizon_months": 6, "priority": "low"},
        ],
    }
    profile.update(overrides)
    return profile


def _plan(**overrides: Any) -> FinancialPlan:
    return plan_for_profile(_profile(**overrides), AS_OF)


def _assert_budget_invariants(plan: FinancialPlan) -> None:
    for b in plan.budgets:
        c = b.currency
        zero = Money.zero(c)
        surplus = b.monthly_surplus.clamp_non_negative()
        # El flujo mensual asignado más lo no asignado es exactamente el excedente.
        assert b.monthly_allocated + b.unassigned_monthly == surplus
        assert b.monthly_allocated <= surplus
        for part in (b.reserve_contribution, b.high_apr_debt_payment, b.goal_contributions, b.unassigned_monthly):
            assert part >= zero
        # La reserva nunca recibe más de lo que le falta.
        assert b.reserve_contribution <= b.reserve_gap
        assert b.reserve_held + b.reserve_gap == b.reserve_target
        # El saldo actual asignado más lo no asignado es exactamente el saldo libre.
        assert b.stock_allocated + b.unassigned_stock == b.free_stock
        # El saldo libre ya descuenta compromisos, ahorros de metas y reserva.
        assert b.free_stock <= (b.liquid_balance - b.reserved_balances - b.goal_savings - b.reserve_target).clamp_non_negative()
        goals = [g for g in plan.goals if g.currency == c]
        assert sum((g.monthly_allocation.amount for g in goals), Decimal(0)) == b.goal_contributions.amount
        assert sum((g.one_time_allocation.amount for g in goals), Decimal(0)) == b.stock_to_goals.amount
        for g in goals:
            assert g.one_time_allocation <= g.remaining
            assert g.monthly_allocation <= g.remaining - g.one_time_allocation


# ── Presupuesto conjunto ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cash,reserve_months,commitment,goal_scale",
    list(itertools.product([0, 8000, 13500, 20000, 100000], [None, 0, 6], [0, 300], [Decimal("0.1"), 1, 10])),
)
def test_three_goals_never_receive_more_than_the_2500_surplus(cash, reserve_months, commitment, goal_scale) -> None:
    profile = _profile(
        assets=[{"name": "Cash", "value": cash, "liquidity": "high"}],
        emergency_reserve_months=reserve_months,
        commitments=[{"name": "Rent increase", "amount": commitment, "kind": "monthly"}] if commitment else [],
    )
    for g in profile["goals"]:
        g["target_amount"] = float(Decimal(str(g["target_amount"])) * Decimal(str(goal_scale)))
    plan = plan_for_profile(profile, AS_OF)
    b = plan.budget("USD")
    assert b is not None
    surplus = Money.of(2500 - commitment, "USD")
    assert b.monthly_surplus == surplus
    total_goal_monthly = sum((g.monthly_allocation.amount for g in plan.goals), Decimal(0))
    assert total_goal_monthly <= Decimal(2500)
    # Las metas solo reciben lo que queda después de reserva y compromisos.
    assert b.goal_contributions <= surplus - b.reserve_contribution - b.high_apr_debt_payment
    _assert_budget_invariants(plan)


def test_reserve_gap_takes_the_surplus_before_goals() -> None:
    plan = _plan()
    b = plan.budget("USD")
    assert b.reserve_target == Money.of(13500, "USD")
    assert b.reserve_gap == Money.of(5500, "USD")
    assert b.reserve_contribution == Money.of(2500, "USD")
    assert b.goal_contributions.is_zero()
    assert b.unassigned_stock.is_zero()
    ids = {c.constraint_id for c in plan.constraints}
    assert {"insufficient_emergency_fund", "goal_shortfall"} <= ids
    assert all(g.status == "underfunded" for g in plan.goals)


def test_current_balance_is_not_mixed_with_future_income() -> None:
    plan = _plan(assets=[{"name": "Cash", "value": 20000, "liquidity": "high"}], goals=[])
    b = plan.budget("USD")
    # La auditoría obtenía 10500 sumando 8000 de saldo y un mes de excedente.
    assert b.free_stock == Money.of(6500, "USD")
    assert b.unassigned_stock == Money.of(6500, "USD")
    assert b.unassigned_monthly == Money.of(2500, "USD")


def test_only_high_liquidity_and_unreserved_balances_are_available() -> None:
    plan = _plan(
        assets=[
            {"name": "Cash", "value": 30000, "liquidity": "high"},
            {"name": "Bond fund", "value": 50000, "liquidity": "medium"},
        ],
        commitments=[{"name": "Tuition", "amount": 5000, "kind": "reserved_balance"}],
        goals=[{"name": "Fund", "target_amount": 10000, "current_amount": 4000, "horizon_months": 12, "priority": "high"}],
    )
    b = plan.budget("USD")
    assert b.other_balances == Money.of(50000, "USD")
    # 30000 - 5000 reservados - 4000 ya ahorrados para la meta - 13500 de reserva.
    assert b.free_stock == Money.of(7500, "USD")
    assert b.stock_to_goals == Money.of(6000, "USD")
    assert b.unassigned_stock == Money.of(1500, "USD")
    _assert_budget_invariants(plan)


def test_commitments_exceeding_liquid_balance_block_investment() -> None:
    plan = _plan(commitments=[{"name": "Tuition", "amount": 9000, "kind": "reserved_balance"}])
    ids = {c.constraint_id for c in plan.blocking_constraints("USD")}
    assert "commitments_exceed_liquid_balance" in ids
    assert plan.budget("USD").free_stock.is_zero()


def test_minimum_payments_flag_changes_the_surplus() -> None:
    debt = [{"name": "Loan", "balance": 5000, "apr": 8, "minimum_payment": 400}]
    unknown = _plan(liabilities=debt)
    included = _plan(liabilities=debt, cashflow={"monthly_income": 7000, "monthly_expenses": 4500, "minimum_payments_included_in_expenses": True})
    excluded = _plan(liabilities=debt, cashflow={"monthly_income": 7000, "monthly_expenses": 4500, "minimum_payments_included_in_expenses": False})
    assert included.budget("USD").monthly_surplus == Money.of(2500, "USD")
    assert excluded.budget("USD").monthly_surplus == Money.of(2100, "USD")
    # Sin declaración, resto los pagos (supuesto conservador) y lo informo.
    assert unknown.budget("USD").monthly_surplus == Money.of(2100, "USD")
    assert "minimum_payments_assumed_not_included_in_expenses" in unknown.assumptions
    assert "minimum_payments_assumed_not_included_in_expenses" not in included.assumptions


def test_high_apr_debt_is_paid_before_goals_and_blocks_investment() -> None:
    plan = _plan(
        assets=[{"name": "Cash", "value": 13500, "liquidity": "high"}],
        liabilities=[{"name": "Card", "balance": 1000, "apr": 22, "minimum_payment": 50}],
        cashflow={"monthly_income": 7000, "monthly_expenses": 4500, "minimum_payments_included_in_expenses": True},
    )
    b = plan.budget("USD")
    assert b.reserve_gap.is_zero()
    assert b.high_apr_debt_payment == Money.of(1000, "USD")
    assert b.goal_contributions == Money.of(1500, "USD")
    assert "high_apr_debt_present" in {c.constraint_id for c in plan.blocking_constraints("USD")}
    _assert_budget_invariants(plan)


def test_debt_ratio_policies_use_their_own_units() -> None:
    plan = _plan(
        assets=[{"name": "Cash", "value": 100000, "liquidity": "high"}],
        liabilities=[{"name": "Mortgage", "balance": 70000, "apr": 5, "minimum_payment": 1500}],
        cashflow={"monthly_income": 7000, "monthly_expenses": 4500, "minimum_payments_included_in_expenses": True},
        goals=[],
    )
    metrics = plan_metrics(plan)
    # 70000 / 7000 = 10 meses de ingreso: no aplico umbrales de carga mensual a esta métrica.
    assert metrics["debt_balance_to_monthly_income"] == 10.0
    assert metrics["debt_service_ratio"] == pytest.approx(0.2143, abs=1e-4)
    ids = {c.constraint_id: c for c in plan.constraints}
    assert ids["high_debt_service_ratio"].severity == "medium"
    assert ids["high_debt_service_ratio"].evidence["unit"] == "minimum_payments / monthly_income"
    assert ids["high_debt_to_assets_ratio"].evidence["unit"] == "debt_balance / total_assets"
    assert "high_debt_to_income_ratio" not in ids


# ── Casos límite ───────────────────────────────────────────────────────────────


def test_deficit_allocates_nothing_and_blocks_investment() -> None:
    plan = _plan(cashflow={"monthly_income": 3000, "monthly_expenses": 3500})
    b = plan.budget("USD")
    assert b.monthly_surplus == Money.of(-500, "USD")
    assert b.monthly_allocated.is_zero()
    assert b.unassigned_monthly.is_zero()
    assert "negative_cashflow" in {c.constraint_id for c in plan.blocking_constraints("USD")}
    _assert_budget_invariants(plan)


def test_zero_income_and_zero_expenses() -> None:
    plan = _plan(cashflow={"monthly_income": 0, "monthly_expenses": 0}, assets=[])
    b = plan.budget("USD")
    assert b.monthly_allocated.is_zero()
    assert b.reserve_target.is_zero()
    assert "zero_income" in {c.constraint_id for c in plan.constraints}
    assert plan_metrics(plan)["savings_rate"] == 0.0
    _assert_budget_invariants(plan)


def test_zero_income_with_expenses_is_a_deficit() -> None:
    plan = _plan(cashflow={"monthly_income": 0, "monthly_expenses": 1000})
    assert "negative_cashflow" in {c.constraint_id for c in plan.constraints}
    assert plan.budget("USD").monthly_allocated.is_zero()


def test_achieved_goal_receives_nothing() -> None:
    plan = _plan(
        assets=[{"name": "Cash", "value": 50000, "liquidity": "high"}],
        goals=[
            {"name": "Done", "target_amount": 5000, "current_amount": 6000, "horizon_months": 6, "priority": "high"},
            {"name": "Open", "target_amount": 5000, "horizon_months": 6, "priority": "low"},
        ],
    )
    done = next(g for g in plan.goals if g.name == "Done")
    assert done.status == "achieved"
    assert done.one_time_allocation.is_zero() and done.monthly_allocation.is_zero()
    assert done.months_to_goal == 0
    _assert_budget_invariants(plan)


def test_overdue_goal_is_reported_without_required_amount() -> None:
    plan = _plan(
        assets=[{"name": "Cash", "value": 13500, "liquidity": "high"}],
        goals=[
            {"name": "Late", "target_amount": 5000, "target_date": "2026-09-01", "priority": "high"},
            {"name": "Today", "target_amount": 5000, "target_date": AS_OF.isoformat(), "priority": "medium"},
        ],
    )
    for g in plan.goals:
        assert g.status == "overdue"
        assert g.required_monthly is None
        assert g.months_left is None
    assert "goal_shortfall" in {c.constraint_id for c in plan.constraints}
    _assert_budget_invariants(plan)


def test_target_date_counts_whole_months_and_short_deadlines_get_one_month() -> None:
    assert whole_months_between(date(2026, 10, 3), date(2027, 4, 3)) == 6
    assert whole_months_between(date(2026, 10, 3), date(2027, 4, 2)) == 5
    plan = _plan(
        assets=[{"name": "Cash", "value": 13500, "liquidity": "high"}],
        goals=[{"name": "Soon", "target_amount": 1000, "target_date": "2026-10-20", "priority": "high"}],
    )
    soon = plan.goals[0]
    assert soon.months_left == 1
    assert soon.required_monthly == Money.of(1000, "USD")
    assert soon.status == "on_track"


def test_more_than_three_goals_are_all_planned_within_budget() -> None:
    goals = [
        {"name": f"G{i}", "target_amount": 4000 + 1000 * i, "horizon_months": 6 + i, "priority": ["high", "medium", "low"][i % 3]}
        for i in range(7)
    ]
    plan = _plan(assets=[{"name": "Cash", "value": 13500, "liquidity": "high"}], goals=goals)
    assert len(plan.goals) == 7
    assert plan.budget("USD").goal_contributions == Money.of(2500, "USD")
    funded = [g for g in plan.goals if g.monthly_allocation.is_positive()]
    # Atiendo primero la prioridad alta y, dentro de ella, el plazo más cercano.
    assert funded[0].priority == "high"
    _assert_budget_invariants(plan)


def test_rounding_keeps_allocations_within_budget() -> None:
    plan = _plan(
        cashflow={"monthly_income": 1000.01, "monthly_expenses": 0},
        assets=[],
        emergency_reserve_months=0,
        goals=[
            {"name": "A", "target_amount": 1000, "horizon_months": 3, "priority": "high"},
            {"name": "B", "target_amount": 1000, "horizon_months": 3, "priority": "high"},
            {"name": "C", "target_amount": 100, "horizon_months": 7, "priority": "high"},
        ],
    )
    a = next(g for g in plan.goals if g.name == "A")
    assert a.required_monthly == Money.of("333.34", "USD")
    b = plan.budget("USD")
    assert b.goal_contributions + b.unassigned_monthly == Money.of("1000.01", "USD")
    _assert_budget_invariants(plan)


def test_required_monthly_is_exact_when_division_is_exact() -> None:
    plan = _plan(assets=[{"name": "Cash", "value": 13500, "liquidity": "high"}])
    required = {g.name: g.required_monthly for g in plan.goals}
    assert required["Trip"] == Money.of(500, "USD")
    assert required["Car"] == Money.of(750, "USD")
    assert required["Down payment"] == Money.of("1111.12", "USD")


def test_sub_cent_inputs_are_rounded_and_reported() -> None:
    plan = _plan(cashflow={"monthly_income": 7000.004, "monthly_expenses": 4500})
    assert plan.budget("USD").monthly_income == Money.of("7000.00", "USD")
    assert any(a.startswith("amounts_rounded_to_currency_minor_unit") for a in plan.assumptions)


# ── Monedas ────────────────────────────────────────────────────────────────────


def test_currencies_keep_separate_budgets_without_implicit_conversion() -> None:
    plan = _plan(
        cashflow={"monthly_income": 2000000, "monthly_expenses": 1500000, "currency": "ARS"},
        currency="ARS",
        assets=[
            {"name": "Pesos", "value": 6000000, "liquidity": "high", "currency": "ARS"},
            {"name": "Dollars", "value": 3000, "liquidity": "high", "currency": "USD"},
        ],
        goals=[{"name": "Trip", "target_amount": 5000, "horizon_months": 12, "priority": "high", "currency": "USD"}],
    )
    ars = plan.budget("ARS")
    usd = plan.budget("USD")
    assert ars.monthly_surplus == Money.of(500000, "ARS")
    # El excedente en pesos no financia la meta en dólares.
    trip = plan.goals[0]
    assert trip.currency == "USD"
    assert trip.monthly_allocation.is_zero()
    assert trip.one_time_allocation == Money.of(3000, "USD")
    assert usd.monthly_income.is_zero()
    ids = {(c.constraint_id, c.currency) for c in plan.constraints}
    assert ("goal_currency_without_income", "USD") in ids
    assert ("goal_shortfall", "USD") in ids
    _assert_budget_invariants(plan)


def test_additional_cashflow_funds_goals_in_its_own_currency() -> None:
    plan = _plan(
        additional_cashflows=[{"currency": "EUR", "monthly_income": 500, "monthly_expenses": 0}],
        goals=[{"name": "EU", "target_amount": 1200, "horizon_months": 12, "priority": "high", "currency": "EUR"}],
    )
    eur = plan.budget("EUR")
    # Sin gastos en EUR, la reserva en EUR es cero y el excedente va a la meta.
    assert eur.goal_contributions == Money.of(100, "EUR")
    assert plan.budget("USD").goal_contributions.is_zero()
    _assert_budget_invariants(plan)


# ── Escenarios y reproducibilidad ──────────────────────────────────────────────


def test_negative_returns_reduce_projections_without_errors() -> None:
    start = Money.of(1000, "USD")
    monthly = Money.of(100, "USD")
    flat = project_balance(start, monthly, 12, Decimal(0))
    negative = project_balance(start, monthly, 12, Decimal("-0.20"))
    assert flat == Money.of(2200, "USD")
    assert negative < flat
    target = Money.of(2200, "USD")
    assert months_to_reach(start, monthly, target, Decimal(0)) == 12
    slower = months_to_reach(start, monthly, target, Decimal("-0.20"))
    assert slower is None or slower > 12
    with pytest.raises(ValueError):
        Scenario("broken", annual_return=Decimal("-1"))


def test_scenarios_are_deterministic_and_limited() -> None:
    snapshot = snapshot_from_profile(_profile(assets=[{"name": "Cash", "value": 13500, "liquidity": "high"}]), AS_OF)
    results = run_scenarios(snapshot)
    names = [r.scenario.name for r in results]
    assert names == ["base", "income_down_20", "expenses_up_10"]
    base, income_down, _ = results
    assert income_down.plan.budget("USD").monthly_surplus == Money.of(1100, "USD")
    assert income_down.plan.budget("USD").goal_contributions < base.plan.budget("USD").goal_contributions
    with pytest.raises(ValueError):
        run_scenarios(snapshot, tuple(Scenario(f"s{i}") for i in range(4)))


def test_same_inputs_produce_identical_plan() -> None:
    profile = _profile(liabilities=[{"name": "Card", "balance": 1200, "apr": 22, "minimum_payment": 60}])
    snapshot = snapshot_from_profile(profile, AS_OF)
    first = json.dumps(plan_to_dict(build_plan(snapshot), run_scenarios(snapshot)), sort_keys=True)
    second = json.dumps(plan_to_dict(build_plan(snapshot_from_profile(profile, AS_OF)), run_scenarios(snapshot)), sort_keys=True)
    assert first == second


def test_plan_has_no_statistical_indicators() -> None:
    snapshot = snapshot_from_profile(_profile(), AS_OF)
    text = json.dumps(plan_to_dict(build_plan(snapshot), run_scenarios(snapshot)))
    assert "probability" not in text
    assert "confidence" not in text


def test_legacy_profile_without_currency_or_flags_still_plans() -> None:
    legacy = {
        "user_id": "legacy",
        "country": "US",
        "risk_tolerance": "low",
        "cashflow": {"monthly_income": 5000.0, "monthly_expenses": 3800.0},
        "assets": [{"name": "Checking", "category": "cash", "value": 4000.0, "liquidity": "high"}],
        "liabilities": [{"name": "Card", "balance": 1200.0, "apr": 22.0, "minimum_payment": None}],
        "goals": [{"name": "Fund", "target_amount": 12000.0, "current_amount": 0.0, "target_date": None, "horizon_months": 12, "priority": "high"}],
        "preferences": {},
    }
    plan = plan_for_profile(legacy, AS_OF)
    assert plan.base_currency == "USD"
    assert "base_currency_defaulted_to_USD" in plan.assumptions
    assert "reserve_months_defaulted_to_3" in plan.assumptions
    assert "minimum_payment_unknown:Card" in plan.missing_data
    _assert_budget_invariants(plan)
