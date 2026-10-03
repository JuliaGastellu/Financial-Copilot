import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";
import { ApiError, newIdempotencyKey } from "../api/client";
import type { MonthlyReview, Page, ProgressEntry, ProgressSource } from "../api/types";
import { StaleBanner } from "../components/Layout";
import { RadioGroup, SelectField, TextField } from "../components/fields";
import { ReviewTable } from "../components/views";
import { Alert, Button, EmptyState, ErrorState, Loading, PageTitle } from "../components/ui";
import { useSubmitGuard } from "../components/useSubmitGuard";
import { useAppData } from "../data/AppData";
import { describeError } from "../data/errors";
import { currentPeriod, formatMoney, formatMonth, parseAmount } from "../i18n/format";
import { useRecalculate } from "./Home";

function recentPeriods(count = 12): string[] {
  const now = new Date();
  return Array.from({ length: count }, (_, i) => currentPeriod(new Date(now.getFullYear(), now.getMonth() - i, 15)));
}

export function ReviewPage() {
  const data = useAppData();
  const recalc = useRecalculate();
  const [period, setPeriod] = useState(currentPeriod());
  const [review, setReview] = useState<MonthlyReview | null>(null);
  const [entries, setEntries] = useState<ProgressEntry[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error" | "no_plan">("loading");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [goalId, setGoalId] = useState("");
  const [amount, setAmount] = useState("");
  const [source, setSource] = useState<ProgressSource>("monthly_surplus");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const { run, pending } = useSubmitGuard();
  const [saved, setSaved] = useState(false);
  const key = useRef<string | null>(null);

  const load = useCallback(async () => {
    setState("loading");
    setLoadError(null);
    try {
      const [r, page] = await Promise.all([
        data.api.request<MonthlyReview>(`/v1/reviews/${period}`),
        data.api.request<Page<ProgressEntry>>(`/v1/progress?limit=50&period=${period}`),
      ]);
      setReview(r);
      setEntries(page.items);
      setState("ready");
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setState("no_plan");
        return;
      }
      setLoadError(describeError(e));
      setState("error");
    }
  }, [data.api, period]);

  useEffect(() => {
    if (data.profile) void load();
  }, [load, data.profile]);

  if (data.status === "loading" && !data.profile) return <Loading />;
  if (data.status === "error") return <ErrorState message={describeError(data.error)} onRetry={() => void data.reload()} />;
  if (!data.profile) return <Navigate to="/alta" replace />;

  const record = async (e: FormEvent) => {
    e.preventDefault();
    const goal = data.goals.find((g) => g.id === goalId);
    const parsed = parseAmount(amount);
    if (!goal) return setFormError("Elegí una meta.");
    if (!parsed || Number(parsed) <= 0) return setFormError("Escribí un monto mayor que cero.");
    setFormError(null);
    setSubmitError(null);
    await run(async () => {
    key.current ??= newIdempotencyKey();
    try {
      await data.api.request("/v1/progress", {
        method: "POST",
        body: { goal_id: goal.id, period, amount: { amount: parsed, currency: goal.target.currency }, source },
        idempotencyKey: key.current,
      });
      key.current = null;
      setAmount("");
      setSaved(true);
      await load();
      await data.reload();
    } catch (err) {
      setSubmitError(describeError(err));
    }
    });
  };

  const remove = async (entry: ProgressEntry) => {
    try {
      await data.api.request(`/v1/progress/${entry.id}`, { method: "DELETE" });
      await load();
      await data.reload();
    } catch (err) {
      setSubmitError(describeError(err));
    }
  };

  const goalName = (id: string) => data.goals.find((g) => g.id === id)?.name ?? "Meta borrada";

  return (
    <div className="stack">
      <PageTitle>Revisión mensual</PageTitle>
      <SelectField
        label="Mes"
        value={period}
        onChange={(v) => {
          setPeriod(v);
          setSaved(false);
          key.current = null;
        }}
        options={recentPeriods().map((p) => ({ value: p, label: formatMonth(p) }))}
      />
      {state === "loading" && <Loading label="Cargando la revisión…" />}
      {state === "error" && loadError && <ErrorState message={loadError} onRetry={() => void load()} />}
      {state === "no_plan" && <EmptyState title="Primero calculá tu plan" action={<Link to="/inicio">Ir a tu situación</Link>} />}
      {state === "ready" && review && (
        <>
          <StaleBanner freshness={review.freshness} onRecalculate={() => void recalc.run().then(load)} pending={recalc.pending} />
          <ReviewTable review={review} />
        </>
      )}
      {state !== "no_plan" && data.goals.length > 0 && (
        <form className="card" onSubmit={record} noValidate aria-labelledby="progress-title">
          <h2 id="progress-title">Registrar un aporte de {formatMonth(period)}</h2>
          {saved && (
            <Alert tone="success">
              <p>Registramos el aporte.</p>
            </Alert>
          )}
          <SelectField
            label="Meta"
            value={goalId}
            onChange={(v) => {
              setGoalId(v);
              key.current = null;
            }}
            options={[{ value: "", label: "Elegí una meta" }, ...data.goals.map((g) => ({ value: g.id, label: g.name }))]}
          />
          <TextField
            label="Monto aportado"
            value={amount}
            onChange={(v) => {
              setAmount(v);
              key.current = null;
            }}
            inputMode="decimal"
            error={formError}
          />
          <RadioGroup
            legend="¿De dónde salió el dinero?"
            name="progress-source"
            value={source}
            onChange={(v) => {
              setSource(v);
              key.current = null;
            }}
            hint="Así no lo contamos dos veces cuando actualices tus saldos o tu ahorro."
            options={[
              { value: "monthly_surplus", label: "Del excedente de este mes (dinero nuevo)" },
              { value: "existing_balance", label: "De ahorros que ya tenía declarados" },
            ]}
          />
          {submitError && (
            <Alert tone="error" title="No pudimos registrar el aporte">
              <p>{submitError}</p>
            </Alert>
          )}
          <Button type="submit" pending={pending} pendingLabel="Registrando…">
            Registrar aporte
          </Button>
        </form>
      )}
      {entries.length > 0 && (
        <section className="card" aria-labelledby="entries-title">
          <h2 id="entries-title">Aportes registrados en {formatMonth(period)}</h2>
          <ul>
            {entries.map((e) => (
              <li key={e.id}>
                {goalName(e.goal_id)}: {formatMoney(e.amount)} ({e.source === "monthly_surplus" ? "del excedente" : "de ahorros previos"}){" "}
                <Button variant="link" onClick={() => void remove(e)} aria-label={`Borrar el aporte a ${goalName(e.goal_id)}`}>
                  Borrar
                </Button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
