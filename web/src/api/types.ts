// Tipos del contrato v1. Reflejan app/schemas/v1.py y app/schemas/plans_v1.py.

export type Money = { amount: string; currency: string };
export type Provenance = "reported" | "estimated" | "unknown";
export type Priority = "low" | "medium" | "high";

export type ProvenanceV1 = {
  monthly_income: Provenance;
  monthly_expenses: Provenance;
  balances: Provenance;
  reserve_months: Provenance;
};

export type CashflowV1 = {
  currency: string;
  monthly_income: string;
  monthly_expenses: string;
  minimum_payments_included_in_expenses: boolean | null;
};

export type AssetV1 = {
  name: string;
  category: "cash" | "equity" | "bond" | "real_estate" | "retirement" | "crypto" | "other";
  liquidity: "high" | "medium" | "low";
  value: Money;
};

export type ProfileV1 = {
  currency: string;
  country?: string | null;
  risk_tolerance?: "low" | "medium" | "high";
  cashflows: CashflowV1[];
  assets: AssetV1[];
  liabilities: unknown[];
  commitments: unknown[];
  emergency_reserve_months: string | null;
  provenance: ProvenanceV1;
};

export type ProfileResponse = { profile: ProfileV1; updated_at: string };

export type GoalInput = {
  name: string;
  target: Money;
  saved?: Money | null;
  priority: Priority;
  target_date?: string | null;
  horizon_months?: number | null;
};

export type Goal = {
  id: string;
  name: string;
  target: Money;
  saved: Money;
  priority: Priority;
  target_date: string | null;
  horizon_months: number | null;
  created_at: string;
  updated_at: string;
};

export type GoalStatus = "achieved" | "funded_now" | "on_track" | "underfunded" | "overdue" | "no_deadline";

export type GoalAllocation = {
  goal_id: string | null;
  goal_name: string;
  currency: string;
  priority: Priority;
  status: GoalStatus;
  target: Money;
  saved: Money;
  remaining: Money;
  one_time_allocation: Money;
  monthly_allocation: Money;
  required_monthly: Money | null;
  shortfall_monthly: Money | null;
  months_left: number | null;
  deadline_source: "target_date" | "horizon_months" | null;
  months_to_goal: number | null;
};

export type CurrencyBudget = {
  currency: string;
  monthly: {
    income: Money;
    expenses: Money;
    minimum_payments_total: Money;
    minimum_payments_added_to_outflow: Money;
    commitments: Money;
    outflow: Money;
    surplus: Money;
    allocations: { emergency_reserve: Money; high_apr_debt: Money; goals: Money };
    allocated_total: Money;
    unassigned: Money;
  };
  current_balances: {
    liquid: Money;
    not_counted_as_available: Money;
    reserved_commitments: Money;
    goal_savings: Money;
    reserve_target: Money;
    reserve_held: Money;
    reserve_gap: Money;
    free_after_reserve: Money;
    allocations: { high_apr_debt: Money; goals: Money };
    allocated_total: Money;
    unassigned: Money;
  };
  debt: { total: Money; high_apr: Money; high_apr_count: number };
};

export type Constraint = {
  constraint_id: string;
  severity: "low" | "medium" | "high";
  currency: string | null;
  message: string;
  evidence: Record<string, string>;
  effect: string;
  blocks_new_investment: boolean;
};

export type PlanResult = {
  as_of: string;
  policy_version: string;
  base_currency: string;
  reserve_months: string;
  budgets: CurrencyBudget[];
  goals: GoalAllocation[];
  constraints: Constraint[];
  assumptions: string[];
  missing_data: string[];
  scenarios: unknown[];
};

export type Plan = {
  id: string;
  version: number;
  status: "active" | "superseded";
  source: "baseline" | "scenario" | "legacy";
  source_scenario_id: string | null;
  as_of: string;
  policy_version: string;
  engine_version: string;
  created_at: string;
  superseded_at: string | null;
  reproducible: boolean;
  snapshot: unknown;
  result: PlanResult | null;
};

export type PlanSummary = Pick<Plan, "id" | "version" | "status" | "source" | "as_of" | "policy_version" | "engine_version" | "created_at">;

export type StaleReason = "inputs_changed" | "policy_changed" | "engine_changed" | "legacy_plan";
export type Freshness = { is_stale: boolean; reasons: StaleReason[] };
export type CurrentPlan = { plan: Plan; freshness: Freshness };

export type Page<T> = { items: T[]; next_cursor: string | null };

export type ScenarioComparisonBudget = {
  currency: string;
  base_monthly_surplus: Money;
  scenario_monthly_surplus: Money;
  base_goal_contributions: Money;
  scenario_goal_contributions: Money;
  goal_contributions_change: Money;
};

export type ScenarioComparisonGoal = {
  goal_id: string | null;
  goal_name: string;
  base_status: GoalStatus | null;
  scenario_status: GoalStatus | null;
  base_monthly_allocation: Money | null;
  scenario_monthly_allocation: Money | null;
  base_months_to_goal: number | null;
  scenario_months_to_goal: number | null;
};

export type Scenario = {
  id: string;
  base_plan_id: string;
  name: string;
  income_change: string;
  expense_change: string;
  annual_return: string;
  status: "simulated" | "adopted";
  adopted_plan_id: string | null;
  created_at: string;
  adopted_at: string | null;
  result: PlanResult;
  comparison: ScenarioComparisonBudget[];
  goal_comparison: ScenarioComparisonGoal[];
};

export type ScenarioSummary = Pick<Scenario, "id" | "base_plan_id" | "name" | "status" | "created_at">;

export type ProgressSource = "monthly_surplus" | "existing_balance";
export type ProgressEntry = { id: string; goal_id: string; period: string; amount: Money; source: ProgressSource; recorded_at: string };

export type ReviewStatus = "met" | "partial" | "not_recorded" | "not_planned" | "extra" | "not_in_plan";
export type MonthlyReview = {
  period: string;
  plan_id: string;
  plan_version: number;
  freshness: Freshness;
  goals: { goal_id: string; goal_name: string; currency: string; planned: Money; recorded: Money; difference: Money; status: ReviewStatus }[];
  totals: { currency: string; planned: Money; recorded: Money; difference: Money }[];
};

export type DeletionResult = { receipt_id: string; deleted_at: string; evidence: Record<string, unknown> };
