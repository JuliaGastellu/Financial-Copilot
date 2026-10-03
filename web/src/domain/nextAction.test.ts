import { expect, test } from "vitest";
import type { PlanResult } from "../api/types";
import demo from "../demo/demo-data.json";
import { nextAction } from "./nextAction";

const base = (demo as unknown as { current: { plan: { result: PlanResult } } }).current.plan.result;

function withMonthly(patch: Record<string, string>, surplus = "1000.00"): PlanResult {
  const copy: PlanResult = structuredClone(base);
  const b = copy.budgets[0];
  const m = (amount: string) => ({ amount, currency: b.currency });
  b.monthly.surplus = m(surplus);
  b.monthly.allocations = {
    emergency_reserve: m(patch.reserve ?? "0.00"),
    high_apr_debt: m(patch.debt ?? "0.00"),
    goals: m(patch.goals ?? "0.00"),
  };
  b.monthly.unassigned = m(patch.unassigned ?? "0.00");
  return copy;
}

test("prioriza el déficit y muestra su valor absoluto", () => {
  const action = nextAction(withMonthly({}, "-500.00"));
  expect(action.kind).toBe("close_deficit");
  expect(action.amount?.amount).toBe("500.00");
});

test.each([
  [{ reserve: "300.00", goals: "700.00" }, "fund_reserve", "300.00"],
  [{ debt: "200.00", goals: "800.00" }, "pay_debt", "200.00"],
  [{ goals: "1000.00" }, "fund_goals", "1000.00"],
  [{ unassigned: "1000.00" }, "assign_surplus", "1000.00"],
  [{}, "review_data", undefined],
])("elige la acción según el reparto del plan", (patch, kind, amount) => {
  const action = nextAction(withMonthly(patch as Record<string, string>));
  expect(action.kind).toBe(kind);
  expect(action.amount?.amount).toBe(amount);
});

test("con los datos de la demo sugiere aportar a metas", () => {
  expect(nextAction(base).kind).toBe("fund_goals");
});
