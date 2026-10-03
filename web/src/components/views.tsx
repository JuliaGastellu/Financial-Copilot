// Vistas de presentación: reciben datos de la API (o de la demo) y no calculan importes.
import type { ReactNode } from "react";
import type { Goal, MonthlyReview, PlanResult, ProfileV1, Provenance, Scenario } from "../api/types";
import { nextAction, type NextAction } from "../domain/nextAction";
import {
  assumptionText,
  constraintText,
  goalStatusText,
  missingDataText,
  reviewStatusText,
} from "../i18n/explanations";
import { formatDate, formatMoney, formatMonth, fractionToPercent } from "../i18n/format";

export function NextActionCard({ result, action }: { result: PlanResult; action?: ReactNode }) {
  const next: NextAction = nextAction(result);
  const amount = formatMoney(next.amount);
  const texts: Record<NextAction["kind"], { title: string; why: string }> = {
    close_deficit: {
      title: `Cerrá una brecha de ${amount} por mes`,
      why: "Tus salidas superan tus ingresos. Mientras eso pase, el plan no reparte dinero en esa moneda.",
    },
    fund_reserve: {
      title: `Separá ${amount} este mes para tu reserva`,
      why: "Tu reserva de emergencia está incompleta. El plan la completa antes que las metas.",
    },
    pay_debt: {
      title: `Pagá ${amount} extra a tu deuda con tasa alta`,
      why: "Después de la reserva, pagar esa deuda cuesta menos que dejarla crecer.",
    },
    fund_goals: {
      title: `Aportá ${amount} a tus metas este mes`,
      why: "El reparto por meta está en tu plan mensual.",
    },
    assign_surplus: {
      title: `Tenés ${amount} sin asignar este mes`,
      why: "Tu reserva y tus metas ya tienen su aporte. Podés crear otra meta o subir un aporte.",
    },
    review_data: {
      title: "Este mes no hay aportes previstos",
      why: "Revisá tus ingresos, gastos y metas para ver si falta algún dato.",
    },
  };
  return (
    <section className="card highlight" aria-labelledby="next-action-title">
      <p className="eyebrow">Próxima acción</p>
      <h2 id="next-action-title">{texts[next.kind].title}</h2>
      <p>{texts[next.kind].why}</p>
      {action}
    </section>
  );
}

export function BudgetCard({ result }: { result: PlanResult }) {
  return (
    <section className="card" aria-labelledby="budget-title">
      <h2 id="budget-title">Presupuesto de este mes</h2>
      {result.budgets.map((b) => (
        <div key={b.currency} className="budget">
          {result.budgets.length > 1 && <h3>En {b.currency}</h3>}
          <dl className="kv">
            <dt>Ingresos</dt>
            <dd>{formatMoney(b.monthly.income)}</dd>
            <dt>Salidas (gastos, pagos mínimos no incluidos y compromisos)</dt>
            <dd>{formatMoney(b.monthly.outflow)}</dd>
            <dt>Disponible para repartir</dt>
            <dd className="strong">{formatMoney(b.monthly.surplus)}</dd>
            <dt>A tu reserva</dt>
            <dd>{formatMoney(b.monthly.allocations.emergency_reserve)}</dd>
            <dt>A deuda con tasa alta</dt>
            <dd>{formatMoney(b.monthly.allocations.high_apr_debt)}</dd>
            <dt>A tus metas</dt>
            <dd>{formatMoney(b.monthly.allocations.goals)}</dd>
            <dt>Sin asignar</dt>
            <dd>{formatMoney(b.monthly.unassigned)}</dd>
          </dl>
        </div>
      ))}
    </section>
  );
}

export function ReasonsCard({ result }: { result: PlanResult }) {
  const important = result.constraints.filter((c) => c.severity !== "low" || c.blocks_new_investment);
  return (
    <section className="card" aria-labelledby="reasons-title">
      <h2 id="reasons-title">Por qué el plan reparte así</h2>
      {important.length === 0 ? (
        <p>No encontramos restricciones que cambien el reparto.</p>
      ) : (
        <ul className="reasons">
          {important.map((c) => {
            const t = constraintText(c);
            return (
              <li key={`${c.constraint_id}-${c.currency ?? ""}`}>
                <strong>{t.title}</strong>
                {c.currency && result.budgets.length > 1 ? ` (${c.currency})` : ""}. {t.effect}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

const PROVENANCE_LABEL: Record<Provenance, string> = { reported: "dato", estimated: "estimación", unknown: "sin dato" };

export function SituationCard({ profile }: { profile: ProfileV1 }) {
  const main = profile.cashflows.find((c) => c.currency === profile.currency) ?? profile.cashflows[0];
  const liquid = profile.assets.filter((a) => a.liquidity === "high");
  const tag = (p: Provenance) => <span className={`tag tag-${p}`}>{PROVENANCE_LABEL[p]}</span>;
  return (
    <section className="card" aria-labelledby="situation-title">
      <h2 id="situation-title">Tu situación declarada</h2>
      <dl className="kv">
        <dt>Ingreso mensual</dt>
        <dd>
          {profile.provenance.monthly_income === "unknown" ? "No lo sabés" : formatMoney({ amount: main.monthly_income, currency: main.currency })}{" "}
          {tag(profile.provenance.monthly_income)}
        </dd>
        <dt>Gasto mensual</dt>
        <dd>
          {profile.provenance.monthly_expenses === "unknown" ? "No lo sabés" : formatMoney({ amount: main.monthly_expenses, currency: main.currency })}{" "}
          {tag(profile.provenance.monthly_expenses)}
        </dd>
        <dt>Saldo disponible</dt>
        <dd>
          {profile.provenance.balances === "unknown"
            ? "No lo sabés"
            : liquid.length === 0
              ? formatMoney({ amount: "0", currency: profile.currency })
              : liquid.map((a) => formatMoney(a.value)).join(" + ")}{" "}
          {tag(profile.provenance.balances)}
        </dd>
        <dt>Meses de reserva</dt>
        <dd>
          {profile.emergency_reserve_months === null ? "Sugerencia del plan" : `${profile.emergency_reserve_months} meses`}{" "}
          {tag(profile.provenance.reserve_months)}
        </dd>
      </dl>
    </section>
  );
}

export function GoalsTable({ result, caption }: { result: PlanResult; caption: string }) {
  if (result.goals.length === 0) return <p>Este plan no tiene metas.</p>;
  return (
    <div className="table-wrap">
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Meta</th>
            <th scope="col">Estado</th>
            <th scope="col">Aporte mensual</th>
            <th scope="col">Aporte inicial</th>
            <th scope="col">Falta por mes</th>
            <th scope="col">Meses hasta la meta</th>
          </tr>
        </thead>
        <tbody>
          {result.goals.map((g) => (
            <tr key={g.goal_id ?? g.goal_name}>
              <th scope="row">{g.goal_name}</th>
              <td>{goalStatusText[g.status]}</td>
              <td>{formatMoney(g.monthly_allocation)}</td>
              <td>{formatMoney(g.one_time_allocation)}</td>
              <td>{g.shortfall_monthly ? formatMoney(g.shortfall_monthly) : "—"}</td>
              <td>{g.months_to_goal ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ScenarioComparison({ scenario }: { scenario: Scenario }) {
  return (
    <section className="card" aria-labelledby={`cmp-${scenario.id}`}>
      <h2 id={`cmp-${scenario.id}`}>{scenario.name}</h2>
      <p className="muted">
        Ingreso {fractionToPercent(scenario.income_change)} · Gastos {fractionToPercent(scenario.expense_change)} · Rendimiento anual{" "}
        {fractionToPercent(scenario.annual_return)}
      </p>
      <div className="table-wrap">
        <table>
          <caption>Comparación por moneda</caption>
          <thead>
            <tr>
              <th scope="col">Moneda</th>
              <th scope="col">Disponible hoy</th>
              <th scope="col">Disponible en el escenario</th>
              <th scope="col">A metas hoy</th>
              <th scope="col">A metas en el escenario</th>
            </tr>
          </thead>
          <tbody>
            {scenario.comparison.map((c) => (
              <tr key={c.currency}>
                <th scope="row">{c.currency}</th>
                <td>{formatMoney(c.base_monthly_surplus)}</td>
                <td>{formatMoney(c.scenario_monthly_surplus)}</td>
                <td>{formatMoney(c.base_goal_contributions)}</td>
                <td>{formatMoney(c.scenario_goal_contributions)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-wrap">
        <table>
          <caption>Comparación por meta</caption>
          <thead>
            <tr>
              <th scope="col">Meta</th>
              <th scope="col">Hoy</th>
              <th scope="col">En el escenario</th>
              <th scope="col">Meses hoy</th>
              <th scope="col">Meses en el escenario</th>
            </tr>
          </thead>
          <tbody>
            {scenario.goal_comparison.map((g) => (
              <tr key={g.goal_id ?? g.goal_name}>
                <th scope="row">{g.goal_name}</th>
                <td>
                  {g.base_status ? goalStatusText[g.base_status] : "—"} · {formatMoney(g.base_monthly_allocation)}
                </td>
                <td>
                  {g.scenario_status ? goalStatusText[g.scenario_status] : "—"} · {formatMoney(g.scenario_monthly_allocation)}
                </td>
                <td>{g.base_months_to_goal ?? "—"}</td>
                <td>{g.scenario_months_to_goal ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function ReviewTable({ review }: { review: MonthlyReview }) {
  return (
    <div className="table-wrap">
      <table>
        <caption>Aportes de {formatMonth(review.period)} frente al plan</caption>
        <thead>
          <tr>
            <th scope="col">Meta</th>
            <th scope="col">Previsto</th>
            <th scope="col">Registrado</th>
            <th scope="col">Diferencia</th>
            <th scope="col">Estado</th>
          </tr>
        </thead>
        <tbody>
          {review.goals.map((g) => (
            <tr key={g.goal_id}>
              <th scope="row">{g.goal_name}</th>
              <td>{formatMoney(g.planned)}</td>
              <td>{formatMoney(g.recorded)}</td>
              <td>{formatMoney(g.difference)}</td>
              <td>{reviewStatusText[g.status]}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          {review.totals.map((t) => (
            <tr key={t.currency}>
              <th scope="row">Total {t.currency}</th>
              <td>{formatMoney(t.planned)}</td>
              <td>{formatMoney(t.recorded)}</td>
              <td>{formatMoney(t.difference)}</td>
              <td />
            </tr>
          ))}
        </tfoot>
      </table>
    </div>
  );
}

export function HowItWasCalculated({ result, createdAt, engineVersion }: { result: PlanResult; createdAt?: string; engineVersion?: string }) {
  return (
    <div className="stack">
      <section className="card" aria-labelledby="how-dates">
        <h2 id="how-dates">Fechas y versiones</h2>
        <dl className="kv">
          <dt>Fecha del cálculo</dt>
          <dd>{formatDate(result.as_of)}</dd>
          {createdAt && (
            <>
              <dt>Guardado</dt>
              <dd>{formatDate(createdAt)}</dd>
            </>
          )}
          <dt>Reglas aplicadas</dt>
          <dd>{result.policy_version}</dd>
          {engineVersion && (
            <>
              <dt>Versión del cálculo</dt>
              <dd>{engineVersion}</dd>
            </>
          )}
          <dt>Meses de reserva usados</dt>
          <dd>{result.reserve_months}</dd>
        </dl>
      </section>
      <section className="card" aria-labelledby="how-formulas">
        <h2 id="how-formulas">Fórmulas</h2>
        <ul>
          <li>Disponible del mes = ingresos − gastos − pagos mínimos no incluidos en gastos − compromisos mensuales.</li>
          <li>Reserva objetivo = meses de reserva × salidas mensuales.</li>
          <li>Saldo libre = saldo de liquidez alta − saldos apartados − ahorros de metas − reserva objetivo.</li>
          <li>Reparto del disponible: primero la reserva, después la deuda con tasa alta y luego las metas, por prioridad y fecha.</li>
          <li>Aporte requerido de una meta = lo que falta ÷ meses restantes, redondeado hacia arriba al centavo.</li>
          <li>Nunca se reparte más que el disponible ni se suman monedas distintas sin una tasa con fecha y fuente.</li>
        </ul>
      </section>
      <section className="card" aria-labelledby="how-assumptions">
        <h2 id="how-assumptions">Supuestos</h2>
        <ul>
          {result.assumptions.map((a) => (
            <li key={a}>{assumptionText(a)}</li>
          ))}
        </ul>
        {result.missing_data.length > 0 && (
          <>
            <h3>Datos que faltan</h3>
            <ul>
              {result.missing_data.map((m) => (
                <li key={m}>{missingDataText(m)}</li>
              ))}
            </ul>
          </>
        )}
      </section>
      <section className="card" aria-labelledby="how-limits">
        <h2 id="how-limits">Límites</h2>
        <ul>
          <li>Es un plan con reglas explícitas: no predice si vas a llegar a tus metas.</li>
          <li>Los meses hasta cada meta no suponen rendimientos de inversión.</li>
          <li>No reemplaza el asesoramiento profesional ni ejecuta operaciones.</li>
        </ul>
      </section>
    </div>
  );
}

export function GoalList({ goals }: { goals: Goal[] }) {
  return (
    <ul className="goal-list">
      {goals.map((g) => (
        <li key={g.id}>
          <strong>{g.name}</strong>: {formatMoney(g.target)} · ahorrado {formatMoney(g.saved)}
          {g.target_date ? ` · para ${formatDate(g.target_date)}` : g.horizon_months ? ` · en ${g.horizon_months} meses` : ""}
        </li>
      ))}
    </ul>
  );
}
