import { useState } from "react";
import type { Api } from "../api/client";
import { describeError } from "../data/errors";
import { Alert, Button } from "./ui";

type Point = { text: string; facts: string[] };
export type Explanation = {
  plan_id: string;
  source: "provider" | "template";
  fallback_reason: string | null;
  summary: Point;
  points: Point[];
};

/** Explicación en palabras del plan ya calculado. No cambia cifras ni decisiones. */
export function PlanExplanation({ api, planId }: { api: Api; planId: string }) {
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      setExplanation(await api.request<Explanation>(`/v1/plans/${planId}/explanation`, { method: "POST" }));
    } catch (e) {
      setError(describeError(e));
    } finally {
      setPending(false);
    }
  };

  return (
    <section className="card" aria-labelledby="explanation-title">
      <h2 id="explanation-title">Tu plan en palabras</h2>
      {!explanation && (
        <>
          <p>Un resumen del reparto con las mismas cifras de tu plan.</p>
          <Button variant="secondary" onClick={() => void load()} pending={pending} pendingLabel="Preparando…">
            Explicar mi plan
          </Button>
        </>
      )}
      {error && (
        <Alert tone="error">
          <p>{error}</p>
        </Alert>
      )}
      {explanation && (
        <div aria-live="polite">
          <p>
            <strong>{explanation.summary.text}</strong>
          </p>
          <ul>
            {explanation.points.map((p, i) => (
              <li key={i}>{p.text}</li>
            ))}
          </ul>
          <p className="muted">
            {explanation.source === "provider"
              ? "Texto redactado automáticamente y verificado contra las cifras de tu plan."
              : "Explicación estándar armada con las cifras de tu plan."}
          </p>
        </div>
      )}
    </section>
  );
}
