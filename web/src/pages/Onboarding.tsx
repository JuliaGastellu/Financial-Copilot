import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, newIdempotencyKey } from "../api/client";
import type { Goal, GoalInput, ProfileV1, Provenance } from "../api/types";
import { AmountField, RadioGroup, SelectField, TextField } from "../components/fields";
import { Alert, Button, PageTitle } from "../components/ui";
import { useSubmitGuard } from "../components/useSubmitGuard";
import { useAppData } from "../data/AppData";
import { describeError } from "../data/errors";
import { parseAmount } from "../i18n/format";

const CURRENCIES = ["ARS", "USD", "EUR", "UYU", "CLP", "MXN", "BRL"].map((c) => ({ value: c, label: c }));

type Amount = { value: string; provenance: Provenance };
type Form = {
  currency: string;
  income: Amount;
  expenses: Amount;
  minimumPayments: "yes" | "no" | "none";
  balance: Amount;
  reserve: "suggested" | "custom" | "unknown";
  reserveMonths: string;
  goalName: string;
  goalAmount: string;
  goalSaved: string;
  deadline: "months" | "date";
  goalMonths: string;
  goalDate: string;
};

const INITIAL: Form = {
  currency: "ARS",
  income: { value: "", provenance: "reported" },
  expenses: { value: "", provenance: "reported" },
  minimumPayments: "none",
  balance: { value: "", provenance: "reported" },
  reserve: "suggested",
  reserveMonths: "3",
  goalName: "",
  goalAmount: "",
  goalSaved: "",
  deadline: "months",
  goalMonths: "12",
  goalDate: "",
};

type Errors = Partial<Record<string, string>>;

function amountError(a: Amount, label: string): string | null {
  if (a.provenance === "unknown") return null;
  if (!a.value.trim()) return `Escribí ${label} o marcá «No lo sé».`;
  return parseAmount(a.value) === null ? "Usá solo números, por ejemplo 1.250.000 o 1250000,50." : null;
}

export function validateStep(step: number, form: Form): Errors {
  const errors: Errors = {};
  if (step === 1) {
    const income = amountError(form.income, "tu ingreso");
    const expenses = amountError(form.expenses, "tus gastos");
    if (income) errors.income = income;
    if (expenses) errors.expenses = expenses;
  }
  if (step === 2) {
    const balance = amountError(form.balance, "tu saldo");
    if (balance) errors.balance = balance;
    if (form.reserve === "custom") {
      const n = Number(form.reserveMonths.replace(",", "."));
      if (!form.reserveMonths.trim() || !Number.isFinite(n) || n < 0 || n > 24) errors.reserveMonths = "Elegí entre 0 y 24 meses.";
    }
  }
  if (step === 3) {
    if (!form.goalName.trim()) errors.goalName = "Poné un nombre a tu meta.";
    const amount = parseAmount(form.goalAmount);
    if (!amount || Number(amount) <= 0) errors.goalAmount = "Escribí cuánto necesitás, mayor que cero.";
    if (form.goalSaved.trim() && parseAmount(form.goalSaved) === null) errors.goalSaved = "Usá solo números o dejalo vacío.";
    if (form.deadline === "months") {
      const m = Number(form.goalMonths);
      if (!Number.isInteger(m) || m < 1 || m > 600) errors.goalMonths = "Elegí un plazo entre 1 y 600 meses.";
    } else if (!/^\d{4}-\d{2}-\d{2}$/.test(form.goalDate)) {
      errors.goalDate = "Elegí una fecha.";
    }
  }
  return errors;
}

export function buildProfile(form: Form): ProfileV1 {
  const amount = (a: Amount) => (a.provenance === "unknown" ? "0" : (parseAmount(a.value) ?? "0"));
  return {
    currency: form.currency,
    cashflows: [
      {
        currency: form.currency,
        monthly_income: amount(form.income),
        monthly_expenses: amount(form.expenses),
        minimum_payments_included_in_expenses: form.minimumPayments === "none" ? null : form.minimumPayments === "yes",
      },
    ],
    assets:
      form.balance.provenance === "unknown"
        ? []
        : [{ name: "Saldo disponible", category: "cash", liquidity: "high", value: { amount: amount(form.balance), currency: form.currency } }],
    liabilities: [],
    commitments: [],
    emergency_reserve_months: form.reserve === "custom" ? form.reserveMonths.replace(",", ".") : null,
    provenance: {
      monthly_income: form.income.provenance,
      monthly_expenses: form.expenses.provenance,
      balances: form.balance.provenance,
      reserve_months: form.reserve === "unknown" ? "unknown" : "reported",
    },
  };
}

export function buildGoal(form: Form): GoalInput {
  const target = { amount: parseAmount(form.goalAmount) ?? "0", currency: form.currency };
  return {
    name: form.goalName.trim(),
    target,
    saved: form.goalSaved.trim() ? { amount: parseAmount(form.goalSaved) ?? "0", currency: form.currency } : null,
    priority: "high",
    horizon_months: form.deadline === "months" ? Number(form.goalMonths) : null,
    target_date: form.deadline === "date" ? form.goalDate : null,
  };
}

export function OnboardingPage() {
  const { api, reload } = useAppData();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [form, setForm] = useState<Form>(INITIAL);
  const [errors, setErrors] = useState<Errors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const { run, pending } = useSubmitGuard();
  // Conservo las claves entre reintentos: un reintento no duplica la meta ni el plan.
  const keys = useRef({ goal: newIdempotencyKey(), plan: newIdempotencyKey() });
  const progress = useRef<{ profile: boolean; goal: Goal | null; goalDirty: boolean; plan: boolean }>({
    profile: false,
    goal: null,
    goalDirty: false,
    plan: false,
  });

  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setForm((f) => ({ ...f, [key]: value }));
    // Si la meta ya se guardó y la persona la corrige, la actualizo en lugar de crear otra.
    if (String(key).startsWith("goal") || key === "deadline") progress.current.goalDirty = true;
    else progress.current.profile = false;
  };

  const next = (e: FormEvent) => {
    e.preventDefault();
    const found = validateStep(step, form);
    setErrors(found);
    if (Object.keys(found).length === 0) setStep((s) => s + 1);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found = validateStep(3, form);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    await run(async () => {
    setSubmitError(null);
    try {
      if (!progress.current.profile) {
        await api.request("/v1/profile", { method: "PUT", body: buildProfile(form) });
        progress.current.profile = true;
      }
      if (!progress.current.goal) {
        progress.current.goal = await api.request<Goal>("/v1/goals", { method: "POST", body: buildGoal(form), idempotencyKey: keys.current.goal });
        progress.current.goalDirty = false;
      } else if (progress.current.goalDirty) {
        progress.current.goal = await api.request<Goal>(`/v1/goals/${progress.current.goal.id}`, { method: "PUT", body: buildGoal(form) });
        progress.current.goalDirty = false;
      }
      if (!progress.current.plan) {
        try {
          await api.request("/v1/plans", { method: "POST", body: {}, idempotencyKey: keys.current.plan });
        } catch (error) {
          // Sin ingreso o gasto conocidos guardo los datos igual y explico qué falta en la situación.
          if (!(error instanceof ApiError && error.code === "required_data_unknown")) throw error;
        }
        progress.current.plan = true;
      }
      await reload();
      navigate("/inicio", { replace: true });
    } catch (error) {
      setSubmitError(describeError(error));
    }
    });
  };

  const errorCount = Object.keys(errors).length;
  return (
    <div className="narrow">
      <PageTitle>Armemos tu plan</PageTitle>
      <p className="muted">
        Paso {step} de 3. Empezamos con lo mínimo; después podés sumar deudas, otros saldos y más metas.
      </p>
      {errorCount > 0 && (
        <Alert tone="error" title="Revisá el formulario">
          <p>{errorCount === 1 ? "Hay un campo para corregir." : `Hay ${errorCount} campos para corregir.`}</p>
        </Alert>
      )}
      {step === 1 && (
        <form onSubmit={next} noValidate aria-labelledby="step1">
          <h2 id="step1">Tu mes</h2>
          <SelectField label="Moneda principal" value={form.currency} onChange={(v) => set("currency", v)} options={CURRENCIES} />
          <AmountField
            label="Ingreso mensual neto"
            currency={form.currency}
            value={form.income.value}
            provenance={form.income.provenance}
            onValueChange={(v) => set("income", { ...form.income, value: v })}
            onProvenanceChange={(p) => set("income", { ...form.income, provenance: p })}
            error={errors.income}
            hint="Lo que te queda después de impuestos. Si varía, usá un promedio y marcá «Estimación»."
          />
          <AmountField
            label="Gasto mensual"
            currency={form.currency}
            value={form.expenses.value}
            provenance={form.expenses.provenance}
            onValueChange={(v) => set("expenses", { ...form.expenses, value: v })}
            onProvenanceChange={(p) => set("expenses", { ...form.expenses, provenance: p })}
            error={errors.expenses}
          />
          {(form.income.provenance === "unknown" || form.expenses.provenance === "unknown") && (
            <Alert tone="info">
              <p>Podés seguir, pero sin una estimación de ingreso y gasto no podemos calcular tu plan todavía.</p>
            </Alert>
          )}
          <RadioGroup
            legend="Si tenés deudas, ¿tus gastos ya incluyen los pagos mínimos?"
            name="minimum-payments"
            value={form.minimumPayments}
            onChange={(v) => set("minimumPayments", v)}
            options={[
              { value: "none", label: "No tengo deudas" },
              { value: "yes", label: "Sí, ya están incluidos" },
              { value: "no", label: "No, van aparte" },
            ]}
          />
          <div className="actions">
            <Button type="submit">Continuar</Button>
          </div>
        </form>
      )}
      {step === 2 && (
        <form onSubmit={next} noValidate aria-labelledby="step2">
          <h2 id="step2">Tu reserva</h2>
          <AmountField
            label="Saldo disponible hoy"
            currency={form.currency}
            value={form.balance.value}
            provenance={form.balance.provenance}
            onValueChange={(v) => set("balance", { ...form.balance, value: v })}
            onProvenanceChange={(p) => set("balance", { ...form.balance, provenance: p })}
            error={errors.balance}
            hint="Dinero que podés usar ya: cuenta, efectivo, caja de ahorro. Cero es un valor válido."
          />
          <RadioGroup
            legend="¿Cuántos meses de gastos querés tener de reserva?"
            name="reserve"
            value={form.reserve}
            onChange={(v) => set("reserve", v)}
            options={[
              { value: "suggested", label: "Usar la sugerencia (3 meses)" },
              { value: "custom", label: "Elegir otra cantidad" },
              { value: "unknown", label: "No lo sé todavía" },
            ]}
          />
          {form.reserve === "custom" && (
            <TextField
              label="Meses de reserva"
              value={form.reserveMonths}
              onChange={(v) => set("reserveMonths", v)}
              inputMode="decimal"
              error={errors.reserveMonths}
            />
          )}
          <div className="actions">
            <Button variant="secondary" onClick={() => setStep(1)}>
              Volver
            </Button>
            <Button type="submit">Continuar</Button>
          </div>
        </form>
      )}
      {step === 3 && (
        <form onSubmit={submit} noValidate aria-labelledby="step3">
          <h2 id="step3">Tu primera meta</h2>
          <TextField label="Nombre de la meta" value={form.goalName} onChange={(v) => set("goalName", v)} error={errors.goalName} maxLength={120} />
          <TextField
            label={`Monto objetivo (${form.currency})`}
            value={form.goalAmount}
            onChange={(v) => set("goalAmount", v)}
            inputMode="decimal"
            error={errors.goalAmount}
          />
          <TextField
            label={`Ya ahorrado para esta meta (${form.currency}, opcional)`}
            value={form.goalSaved}
            onChange={(v) => set("goalSaved", v)}
            inputMode="decimal"
            error={errors.goalSaved}
            hint="Si está dentro del saldo que indicaste, no lo sumes otra vez allí."
          />
          <RadioGroup
            legend="¿Cómo querés indicar el plazo?"
            name="deadline"
            value={form.deadline}
            onChange={(v) => set("deadline", v)}
            options={[
              { value: "months", label: "En meses" },
              { value: "date", label: "Con una fecha" },
            ]}
          />
          {form.deadline === "months" ? (
            <TextField label="Plazo en meses" value={form.goalMonths} onChange={(v) => set("goalMonths", v)} inputMode="numeric" error={errors.goalMonths} />
          ) : (
            <TextField label="Fecha objetivo" type="date" value={form.goalDate} onChange={(v) => set("goalDate", v)} error={errors.goalDate} />
          )}
          {submitError && (
            <Alert tone="error" title="No pudimos guardar">
              <p>{submitError}</p>
            </Alert>
          )}
          <div className="actions">
            <Button variant="secondary" onClick={() => setStep(2)} disabled={pending}>
              Volver
            </Button>
            <Button type="submit" pending={pending} pendingLabel="Guardando…">
              Crear mi plan
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}
