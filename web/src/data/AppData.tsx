import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, createApi, type Api } from "../api/client";
import type { CurrentPlan, Goal, ProfileResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { config } from "../config";

type Status = "loading" | "ready" | "error";

type AppData = {
  api: Api;
  status: Status;
  error: unknown;
  profile: ProfileResponse | null;
  goals: Goal[];
  current: CurrentPlan | null;
  reload: () => Promise<void>;
};

const Ctx = createContext<AppData | null>(null);

/** Lo exporto para pruebas de componentes con datos simulados. */
export const AppDataContext = Ctx;
export type { AppData };

async function orNull<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Datos de la cuenta en memoria. Lo monto con key = sesión para no mezclar cuentas. */
export function AppDataProvider({ children }: { children: ReactNode }) {
  const { getToken, markExpired } = useAuth();
  const api = useMemo(() => createApi(config.apiBaseUrl, getToken, markExpired), [getToken, markExpired]);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<unknown>(null);
  const [profile, setProfile] = useState<ProfileResponse | null>(null);
  const [goals, setGoals] = useState<Goal[]>([]);
  const [current, setCurrent] = useState<CurrentPlan | null>(null);

  const reload = useCallback(async () => {
    setStatus("loading");
    setError(null);
    try {
      const [p, g, c] = await Promise.all([
        orNull(api.request<ProfileResponse>("/v1/profile")),
        api.request<Goal[]>("/v1/goals"),
        orNull(api.request<CurrentPlan>("/v1/plans/current")),
      ]);
      setProfile(p);
      setGoals(g);
      setCurrent(c);
      setStatus("ready");
    } catch (e) {
      setError(e);
      setStatus("error");
    }
  }, [api]);

  useEffect(() => {
    void reload();
    // Cargo una sola vez por sesión; las páginas piden recargar después de cambios.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value = useMemo(() => ({ api, status, error, profile, goals, current, reload }), [api, status, error, profile, goals, current, reload]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppData(): AppData {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAppData must be used inside AppDataProvider");
  return ctx;
}
