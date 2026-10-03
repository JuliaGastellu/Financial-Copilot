import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { CurrentPlan, Goal, MonthlyReview, ProfileResponse, Scenario } from "../api/types";
import { popupCallback, useAuth } from "../auth/AuthContext";
import { DemoBanner, Shell, StaleBanner } from "../components/Layout";
import {
  BudgetCard,
  GoalList,
  GoalsTable,
  HowItWasCalculated,
  NextActionCard,
  ReasonsCard,
  ReviewTable,
  ScenarioComparison,
  SituationCard,
} from "../components/views";
import { Alert, Button, Loading, PageTitle } from "../components/ui";
import demo from "../demo/demo-data.json";

export function LandingPage() {
  const { signIn } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Shell nav={false}>
      <div className="narrow stack">
        <PageTitle>Ordená tu mes y avanzá con tus metas</PageTitle>
        <p>
          Con tu ingreso, tus gastos, tu reserva y tus metas armamos un plan mensual con reglas explícitas: cuánto podés aportar, qué
          conviene primero y cómo cambia si varían tus ingresos.
        </p>
        <ul>
          <li>Mostramos de dónde sale cada número y qué supuestos usamos.</li>
          <li>No calculamos probabilidades ni recomendamos instrumentos de inversión.</li>
          <li>Podés descargar o borrar tus datos cuando quieras.</li>
        </ul>
        {error && (
          <Alert tone="error">
            <p>{error}</p>
          </Alert>
        )}
        <div className="actions">
          <Button
            pending={pending}
            pendingLabel="Abriendo inicio de sesión…"
            onClick={async () => {
              setPending(true);
              setError(null);
              try {
                await signIn();
              } catch {
                setError("No pudimos abrir el inicio de sesión. Volvé a intentar en unos minutos.");
                setPending(false);
              }
            }}
          >
            Iniciar sesión
          </Button>
          <Link className="btn btn-secondary" to="/demo">
            Ver una demo con datos ficticios
          </Link>
        </div>
        <p className="muted">Por seguridad, la sesión no se guarda en este navegador: al recargar, vas a tener que ingresar otra vez.</p>
      </div>
    </Shell>
  );
}

export function CallbackPage() {
  const { completeSignIn } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState(false);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    completeSignIn()
      .then(() => navigate("/inicio", { replace: true }))
      .catch(() => setError(true));
  }, [completeSignIn, navigate]);
  return (
    <Shell nav={false}>
      {error ? (
        <div className="narrow">
          <PageTitle>No pudimos completar el inicio de sesión</PageTitle>
          <p>
            El enlace venció o ya se usó. <Link to="/">Volvé al inicio</Link> e intentá de nuevo.
          </p>
        </div>
      ) : (
        <Loading label="Completando el inicio de sesión…" />
      )}
    </Shell>
  );
}

export function CallbackPopupPage() {
  useEffect(() => {
    void popupCallback().catch(() => undefined);
  }, []);
  return <Loading label="Completando el inicio de sesión…" />;
}

type DemoData = { profile: ProfileResponse; goals: Goal[]; current: CurrentPlan; scenario: Scenario; review: MonthlyReview };

export function DemoPage() {
  const data = demo as unknown as DemoData;
  const result = data.current.plan.result!;
  return (
    <Shell nav={false} banner={<DemoBanner />}>
      <div className="stack">
        <PageTitle>Demo: así se ve un plan</PageTitle>
        <p>
          <Link to="/">Volver al inicio</Link>
        </p>
        <StaleBanner freshness={data.current.freshness} />
        <NextActionCard result={result} />
        <div className="grid">
          <BudgetCard result={result} />
          <ReasonsCard result={result} />
        </div>
        <SituationCard profile={data.profile.profile} />
        <section className="card" aria-labelledby="demo-goals">
          <h2 id="demo-goals">Metas</h2>
          <GoalList goals={data.goals} />
          <GoalsTable result={result} caption="Reparto por meta" />
        </section>
        <ScenarioComparison scenario={data.scenario} />
        <section className="card" aria-labelledby="demo-review">
          <h2 id="demo-review">Revisión mensual</h2>
          <ReviewTable review={data.review} />
        </section>
        <section aria-labelledby="demo-how">
          <h2 id="demo-how">Cómo lo calculé</h2>
          <HowItWasCalculated result={result} />
        </section>
      </div>
    </Shell>
  );
}

export function NotFoundPage() {
  return (
    <Shell nav={false}>
      <div className="narrow">
        <PageTitle>No encontramos esta página</PageTitle>
        <p>
          <Link to="/">Volver al inicio</Link>
        </p>
      </div>
    </Shell>
  );
}
