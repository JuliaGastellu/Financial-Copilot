import { InMemoryWebStorage, UserManager, WebStorageStateStore, type User } from "oidc-client-ts";
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { config } from "../config";

type Status = "signed_out" | "signed_in";

type AuthValue = {
  status: Status;
  /** Identificador estable de la sesión para aislar datos en memoria; nunca lo muestro. */
  sessionKey: string | null;
  sessionExpired: boolean;
  getToken: () => string | null;
  markExpired: () => void;
  signIn: () => Promise<void>;
  reauthenticate: () => Promise<boolean>;
  signOut: () => Promise<void>;
  completeSignIn: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function createUserManager(origin: string = window.location.origin): UserManager {
  return new UserManager({
    authority: config.oidcAuthority,
    client_id: config.oidcClientId,
    redirect_uri: `${origin}/callback`,
    popup_redirect_uri: `${origin}/callback-popup`,
    post_logout_redirect_uri: `${origin}/`,
    response_type: "code",
    scope: "openid",
    // La sesión vive solo en memoria: no guardo tokens en localStorage ni sessionStorage.
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    // El estado temporal de PKCE necesita sobrevivir a la redirección; no es una credencial.
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    automaticSilentRenew: false,
    monitorSession: false,
    loadUserInfo: false,
    extraQueryParams: config.oidcAudience ? { audience: config.oidcAudience } : undefined,
  });
}

export function AuthProvider({ children, manager }: { children: ReactNode; manager?: UserManager }) {
  const managerRef = useRef<UserManager>(manager ?? createUserManager());
  const [user, setUser] = useState<User | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);

  const getToken = useCallback(() => {
    if (!user || user.expired) return null;
    return user.access_token;
  }, [user]);

  const markExpired = useCallback(() => setSessionExpired(true), []);

  const signIn = useCallback(async () => {
    await managerRef.current.signinRedirect();
  }, []);

  const completeSignIn = useCallback(async () => {
    const signedIn = await managerRef.current.signinRedirectCallback();
    setUser(signedIn);
    setSessionExpired(false);
  }, []);

  const reauthenticate = useCallback(async () => {
    try {
      const renewed = await managerRef.current.signinPopup();
      // Si la nueva sesión es de otra cuenta, no reutilizo datos en memoria de la anterior.
      if (user && renewed.profile.sub !== user.profile.sub) {
        setUser(null);
        return false;
      }
      setUser(renewed);
      setSessionExpired(false);
      return true;
    } catch {
      return false;
    }
  }, [user]);

  const signOut = useCallback(async () => {
    const current = user;
    setUser(null);
    setSessionExpired(false);
    await managerRef.current.removeUser();
    if (current?.id_token) {
      try {
        await managerRef.current.signoutRedirect({ id_token_hint: current.id_token });
        return;
      } catch {
        // Si el proveedor no ofrece cierre de sesión, me alcanza con olvidar el token local.
      }
    }
    window.location.assign("/");
  }, [user]);

  const value = useMemo<AuthValue>(
    () => ({
      status: user ? "signed_in" : "signed_out",
      sessionKey: user ? `${user.profile.iss ?? ""}|${user.profile.sub}` : null,
      sessionExpired,
      getToken,
      markExpired,
      signIn,
      reauthenticate,
      signOut,
      completeSignIn,
    }),
    [user, sessionExpired, getToken, markExpired, signIn, reauthenticate, signOut, completeSignIn],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export function popupCallback(): Promise<void> {
  return createUserManager().signinPopupCallback();
}
