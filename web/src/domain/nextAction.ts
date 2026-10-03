// Elijo qué mostrar como próxima acción a partir del plan que calculó la API.
// No calculo importes: solo selecciono los que ya vienen en el resultado.
import type { CurrencyBudget, Money, PlanResult } from "../api/types";

export type NextAction = {
  kind: "close_deficit" | "fund_reserve" | "pay_debt" | "fund_goals" | "assign_surplus" | "review_data";
  amount: Money | null;
  currency: string | null;
};

const positive = (m: Money) => Number(m.amount) > 0;
const negative = (m: Money) => Number(m.amount) < 0;
const absolute = (m: Money): Money => ({ ...m, amount: m.amount.replace(/^-/, "") });

export function baseBudget(result: PlanResult): CurrencyBudget | undefined {
  return result.budgets.find((b) => b.currency === result.base_currency) ?? result.budgets[0];
}

export function nextAction(result: PlanResult): NextAction {
  const deficit = result.budgets.find((b) => negative(b.monthly.surplus));
  if (deficit) return { kind: "close_deficit", amount: absolute(deficit.monthly.surplus), currency: deficit.currency };
  const base = baseBudget(result);
  if (!base) return { kind: "review_data", amount: null, currency: null };
  const { allocations, unassigned } = base.monthly;
  if (positive(allocations.emergency_reserve)) return { kind: "fund_reserve", amount: allocations.emergency_reserve, currency: base.currency };
  if (positive(allocations.high_apr_debt)) return { kind: "pay_debt", amount: allocations.high_apr_debt, currency: base.currency };
  if (positive(allocations.goals)) return { kind: "fund_goals", amount: allocations.goals, currency: base.currency };
  if (positive(unassigned)) return { kind: "assign_surplus", amount: unassigned, currency: base.currency };
  return { kind: "review_data", amount: null, currency: base.currency };
}
