/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

// Política de seguridad de contenido: solo conecto con la API y el proveedor de identidad configurados.
function csp(mode: string): Plugin {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const api = env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
  const idp = env.VITE_OIDC_AUTHORITY || "http://127.0.0.1:8765";
  const policy = [
    "default-src 'self'",
    `connect-src 'self' ${api} ${idp}`,
    "img-src 'self' data:",
    "style-src 'self'",
    "script-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    `form-action 'self' ${idp}`,
    "frame-ancestors 'none'",
  ].join("; ");
  return {
    name: "csp",
    transformIndexHtml(html, ctx) {
      // El servidor de desarrollo inyecta scripts inline; aplico la política al build y a preview.
      return html.replace("%CSP%", ctx.server ? policy.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'").replace("style-src 'self'", "style-src 'self' 'unsafe-inline'") : policy);
    },
  };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), csp(mode)],
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
}));
