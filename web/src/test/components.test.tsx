import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { ApiError, type Api } from "../api/client";
import { AppDataContext, type AppData } from "../data/AppData";
import { buildProfile, OnboardingPage, validateStep } from "../pages/Onboarding";
import { DemoPage } from "../pages/Public";

function renderWithData(ui: ReactNode, api: Partial<Api>, extra: Partial<AppData> = {}) {
  const value: AppData = {
    api: { request: vi.fn(), download: vi.fn(), ...api } as Api,
    status: "ready",
    error: null,
    profile: null,
    goals: [],
    current: null,
    reload: vi.fn().mockResolvedValue(undefined),
    ...extra,
  };
  render(
    <AppDataContext.Provider value={value}>
      <MemoryRouter initialEntries={["/alta"]}>
        <Routes>
          <Route path="/alta" element={ui} />
          <Route path="/inicio" element={<p>Pantalla de inicio</p>} />
        </Routes>
      </MemoryRouter>
    </AppDataContext.Provider>,
  );
  return value;
}

async function fillOnboarding(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/Ingreso mensual neto/), "1.800.000");
  await user.type(screen.getByLabelText(/Gasto mensual/), "1250000");
  await user.click(screen.getByRole("button", { name: "Continuar" }));
  await user.type(await screen.findByLabelText(/Saldo disponible hoy/), "0");
  await user.click(screen.getByRole("button", { name: "Continuar" }));
  await user.type(await screen.findByLabelText("Nombre de la meta"), "Mudanza");
  await user.type(screen.getByLabelText(/Monto objetivo/), "1500000");
}

describe("alta progresiva", () => {
  let setItem: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    setItem = vi.spyOn(Storage.prototype, "setItem");
  });
  afterEach(() => setItem.mockRestore());

  test("distingue dato desconocido, estimado y cero", () => {
    const base = validateStep(1, {
      currency: "ARS",
      income: { value: "", provenance: "unknown" },
      expenses: { value: "", provenance: "reported" },
    } as never);
    expect(base.income).toBeUndefined();
    expect(base.expenses).toMatch(/No lo sé/);

    const profile = buildProfile({
      currency: "ARS",
      income: { value: "1000", provenance: "estimated" },
      expenses: { value: "800", provenance: "reported" },
      minimumPayments: "none",
      balance: { value: "", provenance: "unknown" },
      reserve: "unknown",
      reserveMonths: "",
    } as never);
    expect(profile.assets).toEqual([]);
    expect(profile.provenance).toEqual({ monthly_income: "estimated", monthly_expenses: "reported", balances: "unknown", reserve_months: "unknown" });
    expect(profile.emergency_reserve_months).toBeNull();

    const zero = buildProfile({
      currency: "ARS",
      income: { value: "1000", provenance: "reported" },
      expenses: { value: "800", provenance: "reported" },
      minimumPayments: "yes",
      balance: { value: "0", provenance: "reported" },
      reserve: "suggested",
      reserveMonths: "3",
    } as never);
    expect(zero.assets[0].value).toEqual({ amount: "0", currency: "ARS" });
    expect(zero.cashflows[0].minimum_payments_included_in_expenses).toBe(true);
  });

  test("conserva el formulario ante un fallo y reintenta sin duplicar", async () => {
    const user = userEvent.setup();
    const calls: { path: string; key?: string }[] = [];
    let failGoal = true;
    let releaseProfile: () => void = () => undefined;
    const profileGate = new Promise<void>((resolve) => (releaseProfile = resolve));
    const request = vi.fn(async (path: string, options: { idempotencyKey?: string } = {}) => {
      calls.push({ path, key: options.idempotencyKey });
      // La primera respuesta tarda: así el segundo clic llega con el envío en curso.
      if (path === "/v1/profile") await profileGate;
      if (path === "/v1/goals" && failGoal) {
        failGoal = false;
        throw new ApiError(503, null, "down");
      }
      if (path === "/v1/goals") return { id: "g1" };
      return {};
    });
    const data = renderWithData(<OnboardingPage />, { request: request as unknown as Api["request"] });
    await fillOnboarding(user);

    const submit = screen.getByRole("button", { name: "Crear mi plan" });
    await user.dblClick(submit);
    expect(calls.filter((c) => c.path === "/v1/profile")).toHaveLength(1);
    releaseProfile();
    expect(await screen.findByText(/problema del servicio/)).toBeInTheDocument();
    // El formulario sigue completo después del error.
    expect(screen.getByLabelText("Nombre de la meta")).toHaveValue("Mudanza");
    expect(calls.filter((c) => c.path === "/v1/goals")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Crear mi plan" }));
    expect(await screen.findByText("Pantalla de inicio")).toBeInTheDocument();
    const goalCalls = calls.filter((c) => c.path === "/v1/goals");
    expect(goalCalls).toHaveLength(2);
    expect(goalCalls[0].key).toBe(goalCalls[1].key);
    // El perfil ya estaba guardado: no lo reenvío.
    expect(calls.filter((c) => c.path === "/v1/profile")).toHaveLength(1);
    expect(calls.filter((c) => c.path === "/v1/plans")).toHaveLength(1);
    expect(data.reload).toHaveBeenCalled();
    // Nada del perfil ni de la sesión se guarda en localStorage.
    expect(setItem.mock.contexts.filter((ctx: unknown) => ctx === window.localStorage)).toHaveLength(0);
  });

  test("sin ingreso conocido guarda los datos y explica que falta una estimación", async () => {
    const user = userEvent.setup();
    const request = vi.fn(async (path: string) => {
      if (path === "/v1/plans") throw new ApiError(409, "required_data_unknown", "x");
      if (path === "/v1/goals") return { id: "g1" };
      return {};
    });
    renderWithData(<OnboardingPage />, { request: request as unknown as Api["request"] });
    const income = screen.getByLabelText(/Ingreso mensual neto/);
    const group = income.closest(".amount-field") as HTMLElement;
    await user.click(within(group).getByLabelText("No lo sé"));
    expect(income).toBeDisabled();
    expect(income).toHaveValue("");
    expect(screen.getByText(/sin una estimación de ingreso y gasto no podemos calcular/)).toBeInTheDocument();
  });
});

describe("demo", () => {
  test("está identificada, no ofrece guardar y no muestra indicadores retirados", () => {
    render(
      <MemoryRouter>
        <DemoPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/demo con datos ficticios/i)).toBeInTheDocument();
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/probabilidad|confianza|probability|confidence/i);
    expect(text).not.toMatch(/catálogo|oportunidad/i);
    expect(screen.queryByRole("button", { name: /adoptar|guardar|registrar/i })).toBeNull();
    // No expongo identificadores internos ni el modo del proveedor.
    expect(text).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/);
    expect(text).not.toMatch(/offline|llm/i);
  });
});

describe("aislamiento de sesión", () => {
  test("al cambiar de cuenta se descartan los datos en memoria de la anterior", async () => {
    vi.resetModules();
    const state = { sessionKey: "issuer|alice", token: "token-alice" };
    vi.doMock("../auth/AuthContext", () => ({
      useAuth: () => ({
        status: "signed_in",
        sessionKey: state.sessionKey,
        sessionExpired: false,
        getToken: () => state.token,
        markExpired: () => undefined,
        reauthenticate: async () => true,
        signOut: async () => undefined,
      }),
    }));
    const profiles: Record<string, string> = { "token-alice": "Meta de Alice", "token-bob": "Meta de Bob" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        const token = String((init.headers as Record<string, string>).Authorization).replace("Bearer ", "");
        const body = url.endsWith("/v1/goals")
          ? [{ id: "g", name: profiles[token], target: { amount: "1", currency: "ARS" }, saved: { amount: "0", currency: "ARS" }, priority: "high", target_date: null, horizon_months: 1, created_at: "", updated_at: "" }]
          : url.endsWith("/v1/profile")
            ? { profile: { currency: "ARS", cashflows: [], assets: [], liabilities: [], commitments: [], emergency_reserve_months: null, provenance: {} }, updated_at: "" }
            : null;
        return { ok: body !== null, status: body === null ? 404 : 200, json: async () => body ?? { detail: "Not found." } };
      }),
    );
    const { AppDataProvider, useAppData } = await import("../data/AppData");
    function Goals() {
      const { goals } = useAppData();
      return <ul>{goals.map((g) => <li key={g.id}>{g.name}</li>)}</ul>;
    }
    const view = render(
      <AppDataProvider key={state.sessionKey}>
        <Goals />
      </AppDataProvider>,
    );
    expect(await screen.findByText("Meta de Alice")).toBeInTheDocument();
    state.sessionKey = "issuer|bob";
    state.token = "token-bob";
    view.rerender(
      <AppDataProvider key={state.sessionKey}>
        <Goals />
      </AppDataProvider>,
    );
    await waitFor(() => expect(screen.getByText("Meta de Bob")).toBeInTheDocument());
    expect(screen.queryByText("Meta de Alice")).toBeNull();
    vi.unstubAllGlobals();
    vi.doUnmock("../auth/AuthContext");
  });
});

describe("explicación del plan", () => {
  test("muestra la explicación y aclara si es la estándar", async () => {
    const { PlanExplanation } = await import("../components/PlanExplanation");
    const user = userEvent.setup();
    const request = vi.fn().mockResolvedValue({
      plan_id: "p1",
      source: "template",
      fallback_reason: "provider_disabled",
      summary: { text: "Este mes tenés ARS 550.000,00 para repartir según el plan.", facts: ["f1"] },
      points: [{ text: "«Mudanza» va en camino.", facts: ["f2"] }],
    });
    render(<PlanExplanation api={{ request, download: vi.fn() } as unknown as Api} planId="p1" />);
    await user.click(screen.getByRole("button", { name: "Explicar mi plan" }));
    expect(await screen.findByText(/ARS 550.000,00/)).toBeInTheDocument();
    expect(screen.getByText(/Explicación estándar/)).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith("/v1/plans/p1/explanation", { method: "POST" });
    expect(document.body.textContent).not.toMatch(/provider_disabled|template/);
  });
});
