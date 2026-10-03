// Textos en castellano para los identificadores que devuelve la API.
import type { Constraint, GoalStatus, Provenance, ReviewStatus, StaleReason } from "../api/types";

export const goalStatusText: Record<GoalStatus, string> = {
  achieved: "Cumplida",
  funded_now: "Cubierta con tu saldo actual",
  on_track: "En camino",
  underfunded: "Le falta aporte",
  overdue: "Fecha vencida",
  no_deadline: "Sin fecha",
};

export const reviewStatusText: Record<ReviewStatus, string> = {
  met: "Cumplido",
  partial: "Parcial",
  not_recorded: "Sin registrar",
  not_planned: "Sin aporte previsto",
  extra: "Aporte adicional",
  not_in_plan: "Meta nueva, fuera del plan",
};

export const staleReasonText: Record<StaleReason, string> = {
  inputs_changed: "cambiaron tus datos, tus metas o tus avances",
  policy_changed: "cambiaron las reglas de cálculo",
  engine_changed: "cambió la versión del cálculo",
  legacy_plan: "este plan es anterior al formato actual",
};

export const provenanceText: Record<Provenance, string> = {
  reported: "Dato",
  estimated: "Estimación",
  unknown: "No lo sé",
};

const constraintTitles: Record<string, string> = {
  negative_cashflow: "Tus gastos superan tus ingresos",
  zero_income: "No hay ingresos registrados",
  commitments_exceed_liquid_balance: "Tus compromisos superan tu saldo disponible",
  insufficient_emergency_fund: "Tu reserva está incompleta",
  high_apr_debt_present: "Tenés deuda con tasa alta",
  high_debt_service_ratio: "Los pagos de deuda ocupan mucho de tu ingreso",
  high_debt_to_assets_ratio: "Tu deuda es alta frente a tus activos",
  low_savings_rate: "Tu margen de ahorro es bajo",
  goal_shortfall: "Algunas metas no llegan con este plan",
  goal_currency_without_income: "Tenés metas en una moneda sin ingresos",
};

const constraintEffects: Record<string, string> = {
  negative_cashflow: "Mientras haya déficit, el plan no reparte dinero en esa moneda.",
  zero_income: "Sin ingresos, el plan no asigna aportes mensuales.",
  commitments_exceed_liquid_balance: "No considero libre ninguna parte de tu saldo actual.",
  insufficient_emergency_fund: "El excedente del mes va primero a completar la reserva.",
  high_apr_debt_present: "Después de la reserva, el excedente va a esa deuda antes que a tus metas.",
  high_debt_service_ratio: "No sugiero inversiones nuevas mientras la carga de deuda siga alta.",
  high_debt_to_assets_ratio: "No sugiero inversiones nuevas.",
  low_savings_rate: "Es informativo: no cambia el reparto.",
  goal_shortfall: "Podés sumar ingreso, bajar gastos, mover la fecha o ajustar el monto.",
  goal_currency_without_income: "Esas metas solo reciben saldo de su moneda. Para convertir, hace falta una tasa con fecha y fuente.",
};

export function constraintText(c: Constraint): { title: string; effect: string } {
  return {
    title: constraintTitles[c.constraint_id] ?? "Restricción del plan",
    effect: constraintEffects[c.constraint_id] ?? "",
  };
}

const assumptionTexts: Record<string, string> = {
  only_high_liquidity_balances_count_as_available: "Solo cuento como disponible el dinero de liquidez alta.",
  goal_savings_are_held_within_declared_balances: "Supongo que lo ahorrado para metas está dentro de los saldos que declaraste.",
  reserve_target_uses_total_monthly_outflow: "La reserva se calcula sobre todas tus salidas mensuales, no solo los gastos esenciales.",
  months_to_goal_assume_zero_return: "Los meses hasta cada meta no suponen rendimientos.",
  goal_horizon_months_counted_from_plan_date: "Los plazos en meses se cuentan desde la fecha del plan.",
  minimum_payments_assumed_not_included_in_expenses: "Como no indicaste si tus gastos incluyen los pagos mínimos de deudas, los sumé a las salidas.",
  monthly_income_estimated: "Tu ingreso mensual es una estimación.",
  monthly_expenses_estimated: "Tus gastos mensuales son una estimación.",
  balances_estimated: "Tus saldos son una estimación.",
  reserve_months_estimated: "Los meses de reserva son una estimación.",
};

export function assumptionText(id: string): string {
  if (id.startsWith("reserve_months_defaulted_to_")) {
    return `Como no elegiste los meses de reserva, usé ${id.replace("reserve_months_defaulted_to_", "")} meses como sugerencia.`;
  }
  if (id.startsWith("base_currency_defaulted_to_")) return "No indicaste moneda principal; usé la moneda por defecto.";
  if (id.startsWith("amounts_rounded_to_currency_minor_unit")) return "Redondeé importes a centavos.";
  if (id.startsWith("target_date_used_over_horizon")) return "Para una meta usé la fecha objetivo en lugar del plazo en meses.";
  return assumptionTexts[id] ?? "Supuesto del cálculo.";
}

export function missingDataText(id: string): string {
  if (id === "monthly_income_unknown") return "No sabés tu ingreso mensual.";
  if (id === "monthly_expenses_unknown") return "No sabés tus gastos mensuales.";
  if (id === "balances_unknown") return "No sabés tu saldo disponible: el plan no cuenta saldo actual.";
  if (id === "reserve_months_unknown") return "No elegiste cuántos meses reservar.";
  if (id.startsWith("minimum_payment_unknown")) return "Falta el pago mínimo de una deuda.";
  if (id.startsWith("apr_unknown")) return "Falta la tasa de una deuda.";
  if (id.startsWith("goal_deadline_unknown")) return "Una meta no tiene fecha ni plazo.";
  return "Falta un dato para afinar el cálculo.";
}

export const errorText: Record<string, string> = {
  profile_required: "Primero completá tus datos.",
  required_data_unknown: "Necesitamos al menos una estimación de tu ingreso y tus gastos para calcular el plan.",
  plan_superseded: "Este escenario se armó sobre un plan anterior. Simulalo de nuevo sobre tu plan actual.",
  scenario_already_adopted: "Ya adoptaste este escenario.",
  plan_active: "No se puede borrar el plan vigente.",
  currency_mismatch: "El aporte tiene que estar en la moneda de la meta.",
  future_period: "No se pueden registrar aportes de meses futuros.",
  goal_limit: "Llegaste al máximo de metas.",
  idempotency_key_reused: "Este envío ya se usó con otros datos. Revisá y volvé a intentar.",
  concurrent_update: "Hubo otro cambio al mismo tiempo. Volvé a intentar.",
  not_found: "No encontramos ese dato. Puede que ya no exista.",
};
