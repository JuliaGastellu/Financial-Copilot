import { useEffect, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { newIdempotencyKey } from "../api/client";
import type { Page, PlanSummary } from "../api/types";
import { StaleBanner } from "../components/Layout";
import { BudgetCard, GoalsTable, HowItWasCalculated, NextActionCard, ReasonsCard, SituationCard } from "../components/views";
import { Alert, Button, EmptyState, ErrorState, Loading, PageTitle } from "../components/ui";
import { useSubmitGuard } from "../components/useSubmitGuard";
import { useAppData } from "../data/AppData";
import { describeError } from "../data/errors";
import { formatDate } from "../i18n/format";

/** Calcula un plan nuevo con una clave estable por intento, para que un reintento no duplique versiones. */
export function useRecalculate() {
  const { api, reload } = useAppData();
  const guard = useSubmitGuard();
  const pending = guard.pending;
  const [error, setError] = useState<string | null>(null);
  const key = useRef<string | null>(null);
  const run = () =>
    guard.run(async () => {
      key.current ??= newIdempotencyKey();
      setError(null);
      try {
        await api.request("/v1/plans", { method: "POST", body: {}, idempotencyKey: key.current });
        key.current = null;
        await reload();
      } catch (e) {
        setError(describeError(e));
      }
    });
  return { run, pending, error };
}

function useAccountGate() {
  const data = useAppData();
  if (data.status === "loading" && !data.profile) return { gate: <Loading label="Cargando tu información…" />, data };
  if (data.status === "error") return { gate: <ErrorState message={describeError(data.error)} onRetry={() => void data.reload()} />, data };
  if (!data.profile) return { gate: <Navigate to="/alta" replace />, data };
  return { gate: null, data };
}

export function HomePage() {
  const { gate, data } = useAccountGate();
  const recalc = useRecalculate();
  if (gate) return gate;
  const current = data.current;
  return (
    <div className="stack">
      <PageTitle>Tu situación</PageTitle>
      {recalc.error && (
        <Alert tone="error" title="No pudimos calcular el plan">
          <p>{recalc.error}</p>
        </Alert>
      )}
      {!current || !current.plan.result ? (
        <EmptyState
          title="Todavía no tenés un plan calculado"
          action={
            <Button onClick={() => void recalc.run()} pending={recalc.pending} pendingLabel="Calculando…">
              Calcular mi plan
            </Button>
          }
        >
          <p>Con tus datos y metas armamos un reparto mensual y te mostramos el próximo paso.</p>
        </EmptyState>
      ) : (
        <>
          <StaleBanner freshness={current.freshness} onRecalculate={() => void recalc.run()} pending={recalc.pending} />
          <NextActionCard
            result={current.plan.result}
            action={
              <p>
                <Link to="/plan">Ver el reparto por meta</Link> · <Link to="/como-lo-calcule">Cómo lo calculé</Link>
              </p>
            }
          />
          <div className="grid">
            <BudgetCard result={current.plan.result} />
            <ReasonsCard result={current.plan.result} />
          </div>
        </>
      )}
      {data.profile && <SituationCard profile={data.profile.profile} />}
    </div>
  );
}

const SOURCE: Record<PlanSummary["source"], string> = {
  baseline: "Plan calculado",
  scenario: "Escenario adoptado",
  legacy: "Plan anterior",
};

export function PlanPage() {
  const { gate, data } = useAccountGate();
  const [history, setHistory] = useState<PlanSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const loadHistory = async (from: string | null) => {
    setLoadingHistory(true);
    setHistoryError(null);
    try {
      const page = await data.api.request<Page<PlanSummary>>(`/v1/plans?limit=10${from ? `&cursor=${encodeURIComponent(from)}` : ""}`);
      setHistory((h) => (from ? [...h, ...page.items] : page.items));
      setCursor(page.next_cursor);
    } catch (e) {
      setHistoryError(describeError(e));
    } finally {
      setLoadingHistory(false);
    }
  };

  useEffect(() => {
    if (!gate) void loadHistory(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.current?.plan.id]);

  if (gate) return gate;
  const plan = data.current?.plan;
  return (
    <div className="stack">
      <PageTitle>Plan mensual</PageTitle>
      {!plan?.result ? (
        <EmptyState title="Todavía no tenés un plan" action={<Link to="/inicio">Ir a tu situación</Link>} />
      ) : (
        <>
          <p className="muted">
            Versión {plan.version}, calculada para el {formatDate(plan.as_of)}.
          </p>
          <StaleBanner freshness={data.current!.freshness} />
          <GoalsTable result={plan.result} caption="Reparto por meta" />
          <BudgetCard result={plan.result} />
        </>
      )}
      <section className="card" aria-labelledby="history-title">
        <h2 id="history-title">Historial de versiones</h2>
        {historyError && <ErrorState message={historyError} onRetry={() => void loadHistory(null)} />}
        <ol className="history">
          {history.map((p) => (
            <li key={p.id}>
              Versión {p.version} · {formatDate(p.created_at)} · {SOURCE[p.source]}
              {p.status === "active" ? " · vigente" : ""}
            </li>
          ))}
        </ol>
        {loadingHistory && <Loading label="Cargando versiones…" />}
        {cursor && !loadingHistory && (
          <Button variant="secondary" onClick={() => void loadHistory(cursor)}>
            Ver versiones anteriores
          </Button>
        )}
      </section>
    </div>
  );
}

export function HowPage() {
  const { gate, data } = useAccountGate();
  if (gate) return gate;
  const plan = data.current?.plan;
  return (
    <div className="stack">
      <PageTitle>Cómo lo calculé</PageTitle>
      {!plan?.result ? (
        <EmptyState title="Todavía no hay un plan para explicar" action={<Link to="/inicio">Ir a tu situación</Link>} />
      ) : (
        <HowItWasCalculated result={plan.result} createdAt={plan.created_at} engineVersion={plan.engine_version} />
      )}
    </div>
  );
}
