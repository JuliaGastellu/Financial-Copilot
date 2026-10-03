import { useRef, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { newIdempotencyKey } from "../api/client";
import type { Goal, GoalInput, Priority } from "../api/types";
import { RadioGroup, SelectField, TextField } from "../components/fields";
import { Alert, Button, ConfirmDialog, EmptyState, ErrorState, Loading, PageTitle } from "../components/ui";
import { useSubmitGuard } from "../components/useSubmitGuard";
import { useAppData } from "../data/AppData";
import { describeError } from "../data/errors";
import { formatDate, formatMoney, parseAmount } from "../i18n/format";

type Draft = { name: string; amount: string; saved: string; priority: Priority; deadline: "months" | "date"; months: string; date: string };

const EMPTY: Draft = { name: "", amount: "", saved: "", priority: "medium", deadline: "months", months: "12", date: "" };

function fromGoal(g: Goal): Draft {
  return {
    name: g.name,
    amount: g.target.amount,
    saved: g.saved.amount === "0.00" ? "" : g.saved.amount,
    priority: g.priority,
    deadline: g.target_date ? "date" : "months",
    months: g.horizon_months ? String(g.horizon_months) : "12",
    date: g.target_date ?? "",
  };
}

function validate(d: Draft): Record<string, string> {
  const e: Record<string, string> = {};
  if (!d.name.trim()) e.name = "Poné un nombre a la meta.";
  const amount = parseAmount(d.amount);
  if (!amount || Number(amount) <= 0) e.amount = "Escribí un monto mayor que cero.";
  if (d.saved.trim() && parseAmount(d.saved) === null) e.saved = "Usá solo números o dejalo vacío.";
  if (d.deadline === "months") {
    const m = Number(d.months);
    if (!Number.isInteger(m) || m < 1 || m > 600) e.months = "Elegí un plazo entre 1 y 600 meses.";
  } else if (!/^\d{4}-\d{2}-\d{2}$/.test(d.date)) e.date = "Elegí una fecha.";
  return e;
}

function toInput(d: Draft, currency: string): GoalInput {
  return {
    name: d.name.trim(),
    target: { amount: parseAmount(d.amount) ?? "0", currency },
    saved: d.saved.trim() ? { amount: parseAmount(d.saved) ?? "0", currency } : null,
    priority: d.priority,
    horizon_months: d.deadline === "months" ? Number(d.months) : null,
    target_date: d.deadline === "date" ? d.date : null,
  };
}

export function GoalsPage() {
  const data = useAppData();
  const [editing, setEditing] = useState<Goal | "new" | null>(null);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const { run, pending } = useSubmitGuard();
  const [toDelete, setToDelete] = useState<Goal | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const createKey = useRef<string | null>(null);

  if (data.status === "loading" && !data.profile) return <Loading />;
  if (data.status === "error") return <ErrorState message={describeError(data.error)} onRetry={() => void data.reload()} />;
  if (!data.profile) return <Navigate to="/alta" replace />;
  const currency = data.profile.profile.currency;

  const open = (target: Goal | "new") => {
    setEditing(target);
    setDraft(target === "new" ? EMPTY : fromGoal(target));
    setErrors({});
    setSaveError(null);
    createKey.current = target === "new" ? newIdempotencyKey() : null;
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    const found = validate(draft);
    setErrors(found);
    if (Object.keys(found).length > 0 || !editing) return;
    await run(async () => {
    setSaveError(null);
    try {
      const goalCurrency = editing === "new" ? currency : editing.target.currency;
      if (editing === "new") {
        await data.api.request("/v1/goals", { method: "POST", body: toInput(draft, goalCurrency), idempotencyKey: createKey.current ?? undefined });
      } else {
        await data.api.request(`/v1/goals/${editing.id}`, { method: "PUT", body: toInput(draft, goalCurrency) });
      }
      setEditing(null);
      setMessage("Guardamos la meta. Recalculá tu plan para incluir el cambio.");
      await data.reload();
    } catch (err) {
      setSaveError(describeError(err));
    }
    });
  };

  const remove = async () => {
    if (!toDelete) return;
    await run(async () => {
    try {
      await data.api.request(`/v1/goals/${toDelete.id}`, { method: "DELETE" });
      setToDelete(null);
      setMessage("Borramos la meta. Recalculá tu plan para reflejarlo.");
      await data.reload();
    } catch (err) {
      setSaveError(describeError(err));
      setToDelete(null);
    }
    });
  };

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }));

  return (
    <div className="stack">
      <PageTitle>Metas</PageTitle>
      {message && (
        <Alert tone="success">
          <p>{message}</p>
        </Alert>
      )}
      {data.goals.length === 0 ? (
        <EmptyState title="Todavía no tenés metas" />
      ) : (
        <ul className="cards">
          {data.goals.map((g) => (
            <li key={g.id} className="card">
              <h2>{g.name}</h2>
              <p>
                Objetivo {formatMoney(g.target)} · ahorrado {formatMoney(g.saved)}
                {g.target_date ? ` · para el ${formatDate(g.target_date)}` : g.horizon_months ? ` · en ${g.horizon_months} meses` : ""}
              </p>
              <div className="actions">
                <Button variant="secondary" onClick={() => open(g)} aria-label={`Editar ${g.name}`}>
                  Editar
                </Button>
                <Button variant="danger" onClick={() => setToDelete(g)} aria-label={`Borrar ${g.name}`}>
                  Borrar
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {!editing && <Button onClick={() => open("new")}>Agregar una meta</Button>}
      {editing && (
        <form className="card" onSubmit={save} noValidate aria-labelledby="goal-form-title">
          <h2 id="goal-form-title">{editing === "new" ? "Nueva meta" : `Editar «${editing.name}»`}</h2>
          <TextField label="Nombre" value={draft.name} onChange={(v) => set("name", v)} error={errors.name} maxLength={120} />
          <TextField label={`Monto objetivo (${currency})`} value={draft.amount} onChange={(v) => set("amount", v)} inputMode="decimal" error={errors.amount} />
          <TextField
            label={`Ahorrado para esta meta (${currency})`}
            value={draft.saved}
            onChange={(v) => set("saved", v)}
            inputMode="decimal"
            error={errors.saved}
            hint="Si cambiás este valor, asumimos que ya incluye los aportes que registraste en la revisión mensual."
          />
          <SelectField
            label="Prioridad"
            value={draft.priority}
            onChange={(v) => set("priority", v as Priority)}
            options={[
              { value: "high", label: "Alta" },
              { value: "medium", label: "Media" },
              { value: "low", label: "Baja" },
            ]}
          />
          <RadioGroup
            legend="Plazo"
            name="goal-deadline"
            value={draft.deadline}
            onChange={(v) => set("deadline", v)}
            options={[
              { value: "months", label: "En meses" },
              { value: "date", label: "Con una fecha" },
            ]}
          />
          {draft.deadline === "months" ? (
            <TextField label="Plazo en meses" value={draft.months} onChange={(v) => set("months", v)} inputMode="numeric" error={errors.months} />
          ) : (
            <TextField label="Fecha objetivo" type="date" value={draft.date} onChange={(v) => set("date", v)} error={errors.date} />
          )}
          {saveError && (
            <Alert tone="error" title="No pudimos guardar">
              <p>{saveError}</p>
            </Alert>
          )}
          <div className="actions">
            <Button variant="secondary" onClick={() => setEditing(null)} disabled={pending}>
              Cancelar
            </Button>
            <Button type="submit" pending={pending} pendingLabel="Guardando…">
              Guardar meta
            </Button>
          </div>
        </form>
      )}
      <ConfirmDialog
        open={toDelete !== null}
        title="¿Borrar esta meta?"
        confirmLabel="Borrar meta"
        danger
        pending={pending}
        onCancel={() => setToDelete(null)}
        onConfirm={() => void remove()}
      >
        <p>Se borran también sus avances registrados. Los planes anteriores conservan su historial.</p>
      </ConfirmDialog>
    </div>
  );
}
