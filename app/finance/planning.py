"""Plan financiero determinístico con un presupuesto por moneda.

Separo dos fuentes de dinero que no sumo entre sí:
- el saldo actual (stock), que puede cubrir reserva, deuda cara y metas una sola vez;
- el excedente mensual (flujo), que reparto cada mes.

Ambas siguen la misma cascada: reserva de emergencia, deuda de tasa alta y metas
según prioridad y plazo. Cada peso se asigna una sola vez; lo que sobra queda como
no asignado. Los mismos datos, la misma fecha y la misma política producen el mismo plan.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_CEILING, Decimal
from typing import Any, Literal

from app.finance.model import FinancialSnapshot, Goal, MonthlyCashflow
from app.finance.money import Money, money_min, money_sum, to_decimal
from app.finance.policy import DEFAULT_POLICY, PlanningPolicy

Severity = Literal["low", "medium", "high"]
GoalStatus = Literal["achieved", "funded_now", "on_track", "underfunded", "overdue", "no_deadline"]

_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class PlanConstraint:
    constraint_id: str
    severity: Severity
    currency: str | None
    message: str
    evidence: dict[str, str]
    effect: str
    blocks_new_investment: bool


@dataclass(frozen=True)
class GoalPlan:
    name: str
    currency: str
    priority: str
    status: GoalStatus
    target: Money
    saved: Money
    remaining: Money
    one_time_allocation: Money
    monthly_allocation: Money
    required_monthly: Money | None
    shortfall_monthly: Money | None
    months_left: int | None
    deadline_source: Literal["target_date", "horizon_months"] | None
    months_to_goal: int | None
    goal_id: str | None = None


@dataclass(frozen=True)
class CurrencyBudget:
    currency: str
    # Flujo mensual.
    monthly_income: Money
    monthly_expenses: Money
    minimum_payments_total: Money
    minimum_payments_added: Money
    monthly_commitments: Money
    monthly_outflow: Money
    monthly_surplus: Money
    # Saldo actual.
    liquid_balance: Money
    other_balances: Money
    reserved_balances: Money
    goal_savings: Money
    reserve_target: Money
    reserve_held: Money
    reserve_gap: Money
    free_stock: Money
    total_debt: Money
    high_apr_debt: Money
    high_apr_debt_count: int
    # Asignación del saldo actual.
    stock_to_high_apr_debt: Money
    stock_to_goals: Money
    unassigned_stock: Money
    # Asignación del excedente mensual.
    reserve_contribution: Money
    high_apr_debt_payment: Money
    goal_contributions: Money
    unassigned_monthly: Money

    @property
    def monthly_allocated(self) -> Money:
        return self.reserve_contribution + self.high_apr_debt_payment + self.goal_contributions

    @property
    def stock_allocated(self) -> Money:
        return self.stock_to_high_apr_debt + self.stock_to_goals


@dataclass(frozen=True)
class FinancialPlan:
    as_of: date
    policy_version: str
    base_currency: str
    reserve_months: Decimal
    budgets: tuple[CurrencyBudget, ...]
    goals: tuple[GoalPlan, ...]
    constraints: tuple[PlanConstraint, ...]
    assumptions: tuple[str, ...]
    missing_data: tuple[str, ...]

    def budget(self, currency: str) -> CurrencyBudget | None:
        return next((b for b in self.budgets if b.currency == currency), None)

    def blocking_constraints(self, currency: str) -> list[PlanConstraint]:
        return [c for c in self.constraints if c.blocks_new_investment and c.currency in (None, currency)]


# ── Fechas ─────────────────────────────────────────────────────────────────────


def whole_months_between(start: date, end: date) -> int:
    """Cuento meses completos de `start` a `end`; puede ser negativo."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def _goal_deadline(goal: Goal, as_of: date) -> tuple[int | None, bool, Literal["target_date", "horizon_months"] | None]:
    """Devuelvo (meses restantes, vencida, origen del plazo)."""
    if goal.target_date is not None:
        if goal.target_date <= as_of:
            return None, True, "target_date"
        # Un plazo menor a un mes completo recibe un único aporte mensual.
        return max(1, whole_months_between(as_of, goal.target_date)), False, "target_date"
    if goal.horizon_months is not None:
        return goal.horizon_months, False, "horizon_months"
    return None, False, None


def _ceil_div_months(remaining: Money, monthly: Money) -> int | None:
    if remaining.amount <= 0:
        return 0
    if monthly.amount <= 0:
        return None
    return int((remaining.amount / monthly.amount).to_integral_value(rounding=ROUND_CEILING))


# ── Metas ──────────────────────────────────────────────────────────────────────


def _allocate_goals(
    goals: list[Goal], as_of: date, stock: Money, monthly: Money
) -> tuple[list[GoalPlan], Money, Money]:
    currency = stock.currency
    info: list[dict[str, Any]] = []
    for goal in goals:
        remaining = (goal.target - goal.saved).clamp_non_negative()
        months_left, overdue, source = _goal_deadline(goal, as_of)
        info.append({"goal": goal, "remaining": remaining, "months_left": months_left, "overdue": overdue, "source": source})

    order = sorted(
        (i for i in info if i["remaining"].is_positive()),
        key=lambda i: (
            _PRIORITY_RANK.get(i["goal"].priority, 1),
            i["months_left"] is None,
            i["months_left"] or 0,
            i["goal"].name,
        ),
    )

    one_time: dict[int, Money] = {id(i): Money.zero(currency) for i in info}
    monthly_alloc: dict[int, Money] = {id(i): Money.zero(currency) for i in info}
    required: dict[int, Money | None] = {id(i): None for i in info}

    stock_left = stock
    for i in order:
        give = money_min(stock_left, i["remaining"])
        one_time[id(i)] = give
        stock_left = stock_left - give

    monthly_left = monthly
    # Primero cubro aportes requeridos por plazo, en orden de prioridad y vencimiento.
    for i in order:
        rest = i["remaining"] - one_time[id(i)]
        if not rest.is_positive() or i["months_left"] is None:
            continue
        need = Money(rest.amount / Decimal(i["months_left"]), currency).round_up()
        need = money_min(need, rest)
        required[id(i)] = need
        give = money_min(monthly_left, need)
        monthly_alloc[id(i)] = give
        monthly_left = monthly_left - give
    # Después reparto lo que queda entre metas sin plazo o vencidas.
    for i in order:
        rest = i["remaining"] - one_time[id(i)]
        if not rest.is_positive() or i["months_left"] is not None:
            continue
        give = money_min(monthly_left, rest)
        monthly_alloc[id(i)] = give
        monthly_left = monthly_left - give

    plans: list[GoalPlan] = []
    for i in sorted(info, key=lambda i: (_PRIORITY_RANK.get(i["goal"].priority, 1), i["goal"].name)):
        goal: Goal = i["goal"]
        key = id(i)
        rest = i["remaining"] - one_time[key]
        need = required[key]
        shortfall: Money | None = None
        status: GoalStatus
        if not i["remaining"].is_positive():
            status = "achieved"
        elif not rest.is_positive():
            status = "funded_now"
        elif i["overdue"]:
            status = "overdue"
        elif i["months_left"] is None:
            status = "no_deadline"
        elif need is not None and monthly_alloc[key] >= need:
            status = "on_track"
        else:
            status = "underfunded"
            if need is not None:
                shortfall = need - monthly_alloc[key]
        plans.append(
            GoalPlan(
                name=goal.name,
                currency=currency,
                priority=goal.priority,
                status=status,
                target=goal.target,
                saved=goal.saved,
                remaining=i["remaining"],
                one_time_allocation=one_time[key],
                monthly_allocation=monthly_alloc[key],
                required_monthly=need,
                shortfall_monthly=shortfall,
                months_left=i["months_left"],
                deadline_source=i["source"],
                months_to_goal=_ceil_div_months(rest, monthly_alloc[key]),
                goal_id=goal.goal_id,
            )
        )
    return plans, stock_left, monthly_left


# ── Presupuesto por moneda ─────────────────────────────────────────────────────


def _cashflows_in(snapshot: FinancialSnapshot, currency: str) -> list[MonthlyCashflow]:
    return [c for c in snapshot.cashflows if c.currency == currency]


def _budget_for_currency(
    snapshot: FinancialSnapshot, currency: str, reserve_months: Decimal, policy: PlanningPolicy
) -> tuple[CurrencyBudget, list[GoalPlan]]:
    zero = Money.zero(currency)
    cashflows = _cashflows_in(snapshot, currency)
    income = money_sum((c.income for c in cashflows), currency)
    expenses = money_sum((c.expenses for c in cashflows), currency)

    debts = [d for d in snapshot.debts if d.balance.currency == currency]
    min_payments = money_sum((d.minimum_payment for d in debts if d.minimum_payment is not None), currency)
    included = bool(cashflows) and all(c.minimum_payments_included is True for c in cashflows)
    added = zero if included else min_payments

    monthly_commitments = money_sum(
        (c.amount for c in snapshot.commitments if c.kind == "monthly" and c.amount.currency == currency), currency
    )
    outflow = expenses + added + monthly_commitments
    surplus = income - outflow

    balances = [b for b in snapshot.balances if b.amount.currency == currency]
    liquid = money_sum((b.amount for b in balances if b.liquidity == "high"), currency)
    other = money_sum((b.amount for b in balances if b.liquidity != "high"), currency)
    reserved = money_sum(
        (c.amount for c in snapshot.commitments if c.kind == "reserved_balance" and c.amount.currency == currency), currency
    )
    goals = [g for g in snapshot.goals if g.target.currency == currency]
    goal_savings = money_sum((g.saved for g in goals), currency)

    reserve_target = outflow.times(reserve_months).round_up()
    reserve_base = (liquid - reserved - goal_savings).clamp_non_negative()
    reserve_held = money_min(reserve_base, reserve_target)
    reserve_gap = reserve_target - reserve_held
    free_stock = (reserve_base - reserve_target).clamp_non_negative()

    high_apr = [d for d in debts if d.apr_percent is not None and d.apr_percent >= policy.high_apr_threshold_percent]
    high_apr_balance = money_sum((d.balance for d in high_apr), currency)
    total_debt = money_sum((d.balance for d in debts), currency)

    stock_to_debt = money_min(free_stock, high_apr_balance)
    stock_left = free_stock - stock_to_debt
    debt_left = high_apr_balance - stock_to_debt

    monthly_left = surplus.clamp_non_negative()
    reserve_contribution = money_min(monthly_left, reserve_gap)
    monthly_left = monthly_left - reserve_contribution
    debt_payment = money_min(monthly_left, debt_left)
    monthly_left = monthly_left - debt_payment

    goal_plans, stock_after_goals, monthly_after_goals = _allocate_goals(goals, snapshot.as_of, stock_left, monthly_left)

    budget = CurrencyBudget(
        currency=currency,
        monthly_income=income,
        monthly_expenses=expenses,
        minimum_payments_total=min_payments,
        minimum_payments_added=added,
        monthly_commitments=monthly_commitments,
        monthly_outflow=outflow,
        monthly_surplus=surplus,
        liquid_balance=liquid,
        other_balances=other,
        reserved_balances=reserved,
        goal_savings=goal_savings,
        reserve_target=reserve_target,
        reserve_held=reserve_held,
        reserve_gap=reserve_gap,
        free_stock=free_stock,
        total_debt=total_debt,
        high_apr_debt=high_apr_balance,
        high_apr_debt_count=len(high_apr),
        stock_to_high_apr_debt=stock_to_debt,
        stock_to_goals=stock_left - stock_after_goals,
        unassigned_stock=stock_after_goals,
        reserve_contribution=reserve_contribution,
        high_apr_debt_payment=debt_payment,
        goal_contributions=monthly_left - monthly_after_goals,
        unassigned_monthly=monthly_after_goals,
    )
    return budget, goal_plans


# ── Restricciones ──────────────────────────────────────────────────────────────


def _ratio(numerator: Money, denominator: Money) -> Decimal | None:
    if denominator.amount <= 0:
        return None
    return (numerator.amount / denominator.amount).quantize(Decimal("0.0001"))


def _s(value: Any) -> str:
    if isinstance(value, Money):
        return format(value.round().amount, "f")
    return str(value)


def _constraints_for(budget: CurrencyBudget, goal_plans: list[GoalPlan], is_base: bool, policy: PlanningPolicy) -> list[PlanConstraint]:
    c = budget.currency
    out: list[PlanConstraint] = []

    if budget.monthly_surplus.is_negative():
        out.append(PlanConstraint(
            "negative_cashflow", "high", c,
            f"Monthly outflows exceed monthly income in {c}.",
            {"monthly_surplus": _s(budget.monthly_surplus), "monthly_outflow": _s(budget.monthly_outflow)},
            f"No monthly amount is allocated in {c} until the deficit is closed.",
            True,
        ))
    elif is_base and budget.monthly_income.is_zero():
        out.append(PlanConstraint(
            "zero_income", "high", c,
            f"Monthly income in {c} is zero.",
            {"monthly_income": _s(budget.monthly_income)},
            f"No monthly amount is allocated in {c}.",
            True,
        ))

    committed = budget.reserved_balances + budget.goal_savings
    if committed > budget.liquid_balance:
        out.append(PlanConstraint(
            "commitments_exceed_liquid_balance", "high", c,
            f"Reserved balances and goal savings exceed liquid balances in {c}.",
            {"committed": _s(committed), "liquid_balance": _s(budget.liquid_balance)},
            "No current balance is treated as free.",
            True,
        ))

    if budget.reserve_gap.is_positive():
        months_covered = _ratio(budget.reserve_held, budget.monthly_outflow)
        severity: Severity = "high" if months_covered is None or months_covered < 1 else "medium"
        out.append(PlanConstraint(
            "insufficient_emergency_fund", severity, c,
            f"The emergency reserve in {c} is below its target.",
            {"reserve_target": _s(budget.reserve_target), "reserve_held": _s(budget.reserve_held), "reserve_gap": _s(budget.reserve_gap)},
            f"The monthly surplus goes to the reserve first ({_s(budget.reserve_contribution)} {c}); no current balance is free for new investments.",
            True,
        ))

    if budget.high_apr_debt_count > 0:
        out.append(PlanConstraint(
            "high_apr_debt_present", "medium", c,
            f"Debt with an annual rate of at least {policy.high_apr_threshold_percent}% exists in {c}.",
            {"high_apr_debt": _s(budget.high_apr_debt), "high_apr_debt_count": str(budget.high_apr_debt_count)},
            "Free balance and the surplus left after the reserve go to that debt before goals; new investments are blocked.",
            True,
        ))

    debt_service = _ratio(budget.minimum_payments_total, budget.monthly_income)
    if debt_service is not None and debt_service >= policy.debt_service_medium:
        out.append(PlanConstraint(
            "high_debt_service_ratio", "high" if debt_service >= policy.debt_service_high else "medium", c,
            f"Minimum debt payments take a high share of monthly income in {c}.",
            {"debt_service_ratio": str(debt_service), "unit": "minimum_payments / monthly_income"},
            "New investments are blocked while debt service stays at or above the policy threshold.",
            True,
        ))

    total_assets = budget.liquid_balance + budget.other_balances
    if budget.total_debt.is_positive():
        debt_to_assets = _ratio(budget.total_debt, total_assets)
        if debt_to_assets is None or debt_to_assets >= policy.debt_to_assets_medium:
            out.append(PlanConstraint(
                "high_debt_to_assets_ratio",
                "high" if debt_to_assets is None or debt_to_assets >= policy.debt_to_assets_high else "medium",
                c,
                f"Debt balances are high relative to assets in {c}.",
                {"debt_to_assets_ratio": "undefined" if debt_to_assets is None else str(debt_to_assets), "unit": "debt_balance / total_assets"},
                "New investments are blocked.",
                True,
            ))

    savings_rate = _ratio(budget.monthly_surplus, budget.monthly_income)
    if savings_rate is not None and Decimal(0) <= savings_rate < policy.low_savings_rate:
        out.append(PlanConstraint(
            "low_savings_rate", "low", c,
            f"The monthly surplus is a small share of income in {c}.",
            {"savings_rate": str(savings_rate), "unit": "monthly_surplus / monthly_income"},
            "Informational; it does not change allocations.",
            False,
        ))

    short = [g for g in goal_plans if g.status in ("underfunded", "overdue")]
    if short:
        out.append(PlanConstraint(
            "goal_shortfall", "medium", c,
            f"{len(short)} goal(s) in {c} cannot be met with the current plan.",
            {"goals": ", ".join(g.name for g in short)},
            "No surplus is left for new investments; goals show their monthly shortfall or need a new date.",
            True,
        ))

    if budget.monthly_income.is_zero() and not is_base and any(g.remaining.is_positive() for g in goal_plans):
        out.append(PlanConstraint(
            "goal_currency_without_income", "medium", c,
            f"Goals in {c} have no income in the same currency.",
            {"currency": c},
            f"Goals in {c} only receive current {c} balances; monthly funding needs income in {c} or an explicit conversion with rate, date and source.",
            False,
        ))
    return out


# ── Plan ───────────────────────────────────────────────────────────────────────


def build_plan(snapshot: FinancialSnapshot, policy: PlanningPolicy = DEFAULT_POLICY) -> FinancialPlan:
    assumptions = list(snapshot.assumptions)
    reserve_months = snapshot.reserve_months
    if reserve_months is None:
        reserve_months = policy.default_reserve_months
        assumptions.append(f"reserve_months_defaulted_to_{policy.default_reserve_months}")
    reserve_months = min(max(Decimal(0), reserve_months), policy.max_reserve_months)

    budgets: list[CurrencyBudget] = []
    goal_plans: list[GoalPlan] = []
    constraints: list[PlanConstraint] = []
    for currency in snapshot.currencies():
        budget, goals = _budget_for_currency(snapshot, currency, reserve_months, policy)
        budgets.append(budget)
        goal_plans.extend(goals)
        constraints.extend(_constraints_for(budget, goals, currency == snapshot.base_currency, policy))

    if any(g.deadline_source == "horizon_months" for g in goal_plans):
        assumptions.append("goal_horizon_months_counted_from_plan_date")
    assumptions.append("only_high_liquidity_balances_count_as_available")
    assumptions.append("goal_savings_are_held_within_declared_balances")
    assumptions.append("reserve_target_uses_total_monthly_outflow")
    assumptions.append("months_to_goal_assume_zero_return")

    return FinancialPlan(
        as_of=snapshot.as_of,
        policy_version=policy.version,
        base_currency=snapshot.base_currency,
        reserve_months=reserve_months,
        budgets=tuple(budgets),
        goals=tuple(goal_plans),
        constraints=tuple(constraints),
        assumptions=tuple(dict.fromkeys(assumptions)),
        missing_data=tuple(dict.fromkeys(snapshot.missing_data)),
    )


def available_capital(plan: FinancialPlan, currency: str) -> Money:
    """Saldo actual no asignado: ya descuenta reserva, compromisos, deuda cara y metas."""
    budget = plan.budget(currency)
    return budget.unassigned_stock if budget is not None else Money.zero(currency)


# ── Escenarios ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Scenario:
    name: str
    income_change: Decimal = Decimal(0)
    expense_change: Decimal = Decimal(0)
    annual_return: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        for attr in ("income_change", "expense_change", "annual_return"):
            object.__setattr__(self, attr, to_decimal(getattr(self, attr)))
        if self.income_change < -1 or self.expense_change < -1:
            raise ValueError("Changes cannot reduce a value below zero.")
        if self.annual_return <= -1:
            raise ValueError("Annual return must be greater than -100%.")


DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("base"),
    Scenario("income_down_20", income_change=Decimal("-0.20")),
    Scenario("expenses_up_10", expense_change=Decimal("0.10")),
)


@dataclass(frozen=True)
class GoalProjection:
    name: str
    currency: str
    months_to_goal: int | None
    balance_at_deadline: Money | None


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    plan: FinancialPlan
    projections: tuple[GoalProjection, ...]


def project_balance(start: Money, monthly: Money, months: int, annual_return: Decimal) -> Money:
    """Proyecto saldo con aporte a fin de mes y tasa mensual nominal annual_return / 12."""
    rate = to_decimal(annual_return) / Decimal(12)
    balance = start.amount
    for _ in range(max(0, months)):
        balance = balance * (Decimal(1) + rate) + monthly.amount
    return Money(balance, start.currency).round()


def months_to_reach(start: Money, monthly: Money, target: Money, annual_return: Decimal, max_months: int = 600) -> int | None:
    if start >= target:
        return 0
    rate = to_decimal(annual_return) / Decimal(12)
    balance = start.amount
    for month in range(1, max_months + 1):
        balance = balance * (Decimal(1) + rate) + monthly.amount
        if balance >= target.amount:
            return month
    return None


def apply_scenario(snapshot: FinancialSnapshot, scenario: Scenario) -> FinancialSnapshot:
    cashflows = tuple(
        MonthlyCashflow(
            income=c.income.times(Decimal(1) + scenario.income_change).round(),
            expenses=c.expenses.times(Decimal(1) + scenario.expense_change).round(),
            minimum_payments_included=c.minimum_payments_included,
        )
        for c in snapshot.cashflows
    )
    return replace(snapshot, cashflows=cashflows)


def run_scenarios(
    snapshot: FinancialSnapshot,
    scenarios: tuple[Scenario, ...] = DEFAULT_SCENARIOS,
    policy: PlanningPolicy = DEFAULT_POLICY,
) -> list[ScenarioResult]:
    if len(scenarios) > policy.max_scenarios:
        raise ValueError(f"At most {policy.max_scenarios} scenarios are supported.")
    results: list[ScenarioResult] = []
    for scenario in scenarios:
        plan = build_plan(apply_scenario(snapshot, scenario), policy)
        projections = []
        for g in plan.goals:
            start = g.saved + g.one_time_allocation
            months = months_to_reach(start, g.monthly_allocation, g.target, scenario.annual_return)
            at_deadline = (
                project_balance(start, g.monthly_allocation, g.months_left, scenario.annual_return)
                if g.months_left is not None
                else None
            )
            projections.append(GoalProjection(g.name, g.currency, months, at_deadline))
        results.append(ScenarioResult(scenario, plan, tuple(projections)))
    return results
