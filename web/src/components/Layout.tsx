import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import type { Freshness } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { staleReasonText } from "../i18n/explanations";
import { Alert, Button } from "./ui";

const LINKS = [
  { to: "/inicio", label: "Situación" },
  { to: "/plan", label: "Plan mensual" },
  { to: "/metas", label: "Metas" },
  { to: "/escenarios", label: "Escenarios" },
  { to: "/revision", label: "Revisión mensual" },
  { to: "/como-lo-calcule", label: "Cómo lo calculé" },
  { to: "/cuenta", label: "Cuenta" },
];

export function Shell({ children, nav = true, banner }: { children: ReactNode; nav?: boolean; banner?: ReactNode }) {
  return (
    <>
      <a className="skip-link" href="#contenido">
        Ir al contenido
      </a>
      <header className="site-header">
        <p className="brand">Financial Copilot</p>
        {nav && (
          <nav aria-label="Secciones">
            <ul>
              {LINKS.map((l) => (
                <li key={l.to}>
                  <NavLink to={l.to}>{l.label}</NavLink>
                </li>
              ))}
            </ul>
          </nav>
        )}
      </header>
      {banner}
      <main id="contenido">{children}</main>
      <footer className="site-footer">
        <p>Información educativa basada en reglas explícitas. No es asesoramiento profesional ni ejecuta operaciones.</p>
      </footer>
    </>
  );
}

export function SessionExpiredBanner() {
  const { sessionExpired, reauthenticate } = useAuth();
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  if (!sessionExpired) return null;
  return (
    <div className="banner">
      <Alert tone="warning" title="Tu sesión venció">
        <p>Lo que escribiste sigue en pantalla. Iniciá sesión de nuevo y volvé a enviar.</p>
        {failed && <p>No se pudo iniciar sesión. Si el navegador bloqueó la ventana, permitila y volvé a intentar.</p>}
        <Button
          pending={pending}
          pendingLabel="Abriendo inicio de sesión…"
          onClick={async () => {
            setPending(true);
            const ok = await reauthenticate();
            setFailed(!ok);
            setPending(false);
          }}
        >
          Iniciar sesión de nuevo
        </Button>
      </Alert>
    </div>
  );
}

export function DemoBanner() {
  return (
    <div className="banner">
      <Alert tone="info" title="Estás viendo una demo con datos ficticios">
        <p>Nada de lo que ves se guarda ni representa a una persona real. Para tu propio plan, creá una cuenta.</p>
      </Alert>
    </div>
  );
}

export function StaleBanner({ freshness, onRecalculate, pending }: { freshness: Freshness; onRecalculate?: () => void; pending?: boolean }) {
  if (!freshness.is_stale) return null;
  return (
    <Alert tone="warning" title="Tu plan está desactualizado">
      <p>Desde que lo calculaste, {freshness.reasons.map((r) => staleReasonText[r]).join(" y ")}.</p>
      {onRecalculate && (
        <Button onClick={onRecalculate} pending={pending} pendingLabel="Recalculando…">
          Recalcular plan
        </Button>
      )}
    </Alert>
  );
}
