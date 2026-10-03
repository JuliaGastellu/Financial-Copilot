import { useId, type InputHTMLAttributes, type ReactNode } from "react";
import type { Provenance } from "../api/types";
import { provenanceText } from "../i18n/explanations";

type FieldProps = Omit<InputHTMLAttributes<HTMLInputElement>, "onChange" | "value"> & {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  value: string;
  onChange: (value: string) => void;
};

export function TextField({ label, hint, error, value, onChange, id, ...rest }: FieldProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className="field">
      <label htmlFor={inputId}>{label}</label>
      {hint && (
        <p className="hint" id={hintId}>
          {hint}
        </p>
      )}
      <input
        id={inputId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        {...rest}
      />
      {error && (
        <p className="field-error" id={errorId}>
          {error}
        </p>
      )}
    </div>
  );
}

export function RadioGroup<T extends string>({
  legend,
  name,
  value,
  options,
  onChange,
  hint,
}: {
  legend: string;
  name: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  hint?: string;
}) {
  const hintId = useId();
  return (
    <fieldset className="radio-group" aria-describedby={hint ? hintId : undefined}>
      <legend>{legend}</legend>
      {hint && (
        <p className="hint" id={hintId}>
          {hint}
        </p>
      )}
      {options.map((o) => (
        <label key={o.value} className="radio">
          <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} />
          {o.label}
        </label>
      ))}
    </fieldset>
  );
}

/**
 * Importe con su procedencia. «No lo sé» deja el campo vacío: un dato desconocido
 * no se convierte en cero.
 */
export function AmountField({
  label,
  currency,
  value,
  provenance,
  onValueChange,
  onProvenanceChange,
  error,
  hint,
  allowUnknown = true,
}: {
  label: string;
  currency: string;
  value: string;
  provenance: Provenance;
  onValueChange: (value: string) => void;
  onProvenanceChange: (value: Provenance) => void;
  error?: string | null;
  hint?: string;
  allowUnknown?: boolean;
}) {
  const name = useId();
  const options = (["reported", "estimated", "unknown"] as Provenance[])
    .filter((p) => allowUnknown || p !== "unknown")
    .map((p) => ({ value: p, label: provenanceText[p] }));
  return (
    <div className="amount-field">
      <TextField
        label={`${label} (${currency})`}
        hint={hint}
        error={error}
        value={provenance === "unknown" ? "" : value}
        onChange={onValueChange}
        inputMode="decimal"
        autoComplete="off"
        disabled={provenance === "unknown"}
        placeholder={provenance === "unknown" ? "Sin dato" : "0"}
      />
      <RadioGroup
        legend={`¿Qué tan seguro es este importe?`}
        name={name}
        value={provenance}
        options={options}
        onChange={onProvenanceChange}
      />
    </div>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {hint && (
        <p className="hint" id={`${id}-hint`}>
          {hint}
        </p>
      )}
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)} aria-describedby={hint ? `${id}-hint` : undefined}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
