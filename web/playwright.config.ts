import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Levanto el proveedor OIDC local, la API con una base temporal y la aplicación compilada.
// Todo usa datos ficticios; las capturas quedan en PW_OUTPUT_DIR (por defecto, test-results, ignorado por Git).
const python = process.env.E2E_PYTHON ?? "python";
const dataDir = process.env.E2E_DATA_DIR ?? mkdtempSync(join(tmpdir(), "fc-e2e-"));
const API = "http://127.0.0.1:18100";
const IDP = "http://127.0.0.1:18765";
const WEB = "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "e2e",
  outputDir: process.env.PW_OUTPUT_DIR ?? "test-results",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: WEB,
    channel: "chrome",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "escritorio", use: { viewport: { width: 1280, height: 800 } } },
    { name: "movil-360", use: { viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true } },
  ],
  webServer: [
    {
      command: `${python} scripts/dev_oidc_provider.py --port 18765 --audience financial-copilot-e2e`,
      cwd: "..",
      url: `${IDP}/.well-known/openid-configuration`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `${python} -m uvicorn app.main:app --host 127.0.0.1 --port 18100`,
      cwd: "..",
      url: `${API}/health`,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        ENVIRONMENT: "local",
        DATA_DIR: dataDir,
        OFFLINE_MODE: "true",
        OIDC_ISSUER: IDP,
        OIDC_AUDIENCE: "financial-copilot-e2e",
        OIDC_JWKS_URL: `${IDP}/jwks`,
        OIDC_LEEWAY_SECONDS: "0",
        ALLOWED_ORIGINS: JSON.stringify([WEB]),
        RATE_LIMIT_ENABLED: "false",
      },
    },
    {
      command: "npx vite build && npx vite preview",
      url: WEB,
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_API_BASE_URL: API, VITE_OIDC_AUTHORITY: IDP, VITE_OIDC_CLIENT_ID: "financial-copilot-web" },
    },
  ],
});
