import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";
import { newIdempotencyKey } from "../api/client";
import type { Page, Scenario, ScenarioSummary } from "../api/types";
import { TextField } from "../components/fields";
import { ScenarioComparison } from "../components/views";
import { Alert, Button, ConfirmDialog, EmptyState, ErrorState, Loading, PageTitle } from "../components/ui";
import { useSubmitGuard } from "../components/useSubmitGuard";
import { useAppData } from "../data/AppData";
import { describeError } from "../data/errors";
import { percentToFraction } from "../i18n/format";

type Draft = { name: string; income: string; expenses: string; returns: string };

export function ScenariosPage() {
  const data = useAppData();
  const [draft, setDraft] = useState<Draft>({ name: "Ingreso 20% menor", income: "-20", expenses: "0", returns: "0" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [previous, setPrevious] = useState<ScenarioSummary[]>([]);
  const { run, pending } = useSubmitGuard();
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [adopted, setAdopted] = useState(false);
  const simulateKey = useRef<string | null>(null);
  const adoptKey = useRef<string | null>(null);
  const planId = data.current?.plan.id;

  useEffect(() => {
    if (!planId) return;
    data.api
      .request<Page<ScenarioSummary>>(`/v1/scenarios?limit=10&plan_id=${encodeURIComponent(planId)}`)
      .then((page) => setPrevious(page.items))
      .catch(() => setPrevious([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planId, scenario?.id]);

  if (data.status === "loading" && !data.profile) return <Loading />;
  if (data.status === "error") return <ErrorState message={describeError(data.error)} onRetry={() => void data.reload()} />;
  if (!data.profile) return <Navigate to="/alta" replace />;
  if (!data.current?.plan.result) {
    return (
      <div className="stack">
        <PageTitle>Escenarios</PageTitle>
        <EmptyState title="Primero calculá tu plan" action={<Link to="/inicio">Ir a tu situación</Link>} />
      </div>
    );
  }

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => {
    setDraft((d) => ({ ...d, [k]: v }));
    simulateKey.current = null;
  };

  const simulate = async (e: FormEvent) => {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!draft.name.trim()) found.name = "Poné un nombre al escenario.";
    const income = percentToFraction(draft.income);
    const expenses = percentToFraction(draft.expenses);
    const returns = percentToFraction(draft.returns);
    if (income === null || Number(income) < -1 || Number(income) > 5) found.income = "Escribí un porcentaje entre -100 y 500.";
    if (expenses === null || Number(expenses) < -1 || Number(expenses) > 5) found.expenses = "Escribí un porcentaje entre -100 y 500.";
    if (returns === null || Number(returns) <= -1 || Number(returns) > 1) found.returns = "Escribí un porcentaje mayor que -100 y hasta 100.";
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    await run(async () => {
    simulateKey.current ??= newIdempotencyKey();
    setError(null);
    setAdopted(false);
    try {
      const created = await data.api.request<Scenario>("/v1/scenarios", {
        method: "POST",
        body: { base_plan_id: planId, name: draft.name.trim(), income_change: income, expense_change: expenses, annual_return: returns },
        idempotencyKey: simulateKey.current,
      });
      setScenario(created);
      simulateKey.current = null;
      adoptKey.current = null;
    } catch (err) {
      setError(describeError(err));
    }
    });
  };

  const open = async (id: string) => {
    setError(null);
    try {
      setScenario(await data.api.request<Scenario>(`/v1/scenarios/${id}`));
      adoptKey.current = null;
    } catch (err) {
      setError(describeError(err));
    }
  };

  const adopt = async () => {
    if (!scenario) return;
    await run(async () => {
    adoptKey.current ??= newIdempotencyKey();
    setError(null);
    try {
      await data.api.request(`/v1/scenarios/${scenario.id}/adoption`, { method: "POST", idempotencyKey: adoptKey.current });
      setConfirming(false);
      setAdopted(true);
      setScenario(null);
      await data.reload();
    } catch (err) {
      setConfirming(false);
      setError(describeError(err));
    }
    });
  };

  return (
    <div className="stack">
      <PageTitle>Escenarios</PageTitle>
      <p>Probá qué pasa si cambian tus ingresos o tus gastos. Simular no cambia tu plan; solo lo cambia «Adoptar».</p>
      {adopted && (
        <Alert tone="success" title="Adoptaste el escenario">
          <p>
            Creamos una nueva versión de tu plan. La anterior queda en el historial. <Link to="/plan">Ver el plan</Link>
          </p>
        </Alert>
      )}
      <form className="card" onSubmit={simulate} noValidate aria-labelledby="scenario-form-title">
        <h2 id="scenario-form-title">Nuevo escenario</h2>
        <TextField label="Nombre" value={draft.name} onChange={(v) => set("name", v)} error={errors.name} maxLength={80} />
        <TextField
          label="Cambio de ingreso (%)"
          hint="Negativo si baja. Por ejemplo, -20 es una caída de 20%."
          value={draft.income}
          onChange={(v) => set("income", v)}
          inputMode="decimal"
          error={errors.income}
        />
        <TextField label="Cambio de gastos (%)" value={draft.expenses} onChange={(v) => set("expenses", v)} inputMode="decimal" error={errors.expenses} />
        <TextField
          label="Rendimiento anual supuesto (%)"
          hint="Solo cambia las proyecciones de saldo. Puede ser negativo."
          value={draft.returns}
          onChange={(v) => set("returns", v)}
          inputMode="decimal"
          error={errors.returns}
        />
        {error && (
          <Alert tone="error" title="No pudimos completar la acción">
            <p>{error}</p>
          </Alert>
        )}
        <div className="actions">
          <Button type="submit" pending={pending && !confirming} pendingLabel="Simulando…">
            Simular
          </Button>
        </div>
      </form>
      {scenario && (
        <>
          <ScenarioComparison scenario={scenario} />
          {scenario.status === "simulated" ? (
            <Button onClick={() => setConfirming(true)}>Adoptar este escenario</Button>
          ) : (
            <p className="muted">Este escenario ya fue adoptado.</p>
          )}
        </>
      )}
      {previous.length > 0 && (
        <section className="card" aria-labelledby="previous-title">
          <h2 id="previous-title">Escenarios sobre tu plan actual</h2>
          <ul>
            {previous.map((s) => (
              <li key={s.id}>
                <Button variant="link" onClick={() => void open(s.id)}>
                  {s.name}
                </Button>
                {s.status === "adopted" ? " · adoptado" : ""}
              </li>
            ))}
          </ul>
        </section>
      )}
      <ConfirmDialog
        open={confirming}
        title="¿Adoptar este escenario?"
        confirmLabel="Adoptar"
        pending={pending}
        onCancel={() => setConfirming(false)}
        onConfirm={() => void adopt()}
      >
        <p>Vamos a crear una nueva versión de tu plan con estas hipótesis. Tu plan actual queda en el historial y tus datos declarados no cambian.</p>
      </ConfirmDialog>
    </div>
  );
}
