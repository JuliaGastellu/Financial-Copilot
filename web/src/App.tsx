import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { SessionExpiredBanner, Shell } from "./components/Layout";
import { AppDataProvider } from "./data/AppData";
import { AccountPage } from "./pages/Account";
import { GoalsPage } from "./pages/Goals";
import { HomePage, HowPage, PlanPage } from "./pages/Home";
import { OnboardingPage } from "./pages/Onboarding";
import { CallbackPage, CallbackPopupPage, DemoPage, LandingPage, NotFoundPage } from "./pages/Public";
import { ReviewPage } from "./pages/Review";
import { ScenariosPage } from "./pages/Scenarios";

/** Rutas privadas. Remonto los datos por sesión: otra cuenta nunca ve datos en memoria de la anterior. */
function PrivateArea() {
  const { status, sessionKey } = useAuth();
  if (status === "signed_out" || !sessionKey) return <Navigate to="/" replace />;
  return (
    <AppDataProvider key={sessionKey}>
      <Shell banner={<SessionExpiredBanner />}>
        <Outlet />
      </Shell>
    </AppDataProvider>
  );
}

function Home() {
  const { status } = useAuth();
  return status === "signed_in" ? <Navigate to="/inicio" replace /> : <LandingPage />;
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/callback" element={<CallbackPage />} />
      <Route path="/callback-popup" element={<CallbackPopupPage />} />
      <Route path="/demo" element={<DemoPage />} />
      <Route element={<PrivateArea />}>
        <Route path="/alta" element={<OnboardingPage />} />
        <Route path="/inicio" element={<HomePage />} />
        <Route path="/plan" element={<PlanPage />} />
        <Route path="/metas" element={<GoalsPage />} />
        <Route path="/escenarios" element={<ScenariosPage />} />
        <Route path="/revision" element={<ReviewPage />} />
        <Route path="/como-lo-calcule" element={<HowPage />} />
        <Route path="/cuenta" element={<AccountPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
