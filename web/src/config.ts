// Configuración pública de la aplicación. No contiene secretos.
export const config = {
  apiBaseUrl: (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8000",
  oidcAuthority: (import.meta.env.VITE_OIDC_AUTHORITY as string | undefined) ?? "http://127.0.0.1:8765",
  oidcClientId: (import.meta.env.VITE_OIDC_CLIENT_ID as string | undefined) ?? "financial-copilot-web",
  oidcAudience: (import.meta.env.VITE_OIDC_AUDIENCE as string | undefined) || undefined,
};
