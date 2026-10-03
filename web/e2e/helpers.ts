import { expect, type Page, type TestInfo } from "@playwright/test";

export function subject(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Inicio sesión con el proveedor local. `lifetime` acorta la sesión para probar vencimientos. */
export async function signIn(page: Page, who: string, lifetime?: number) {
  await page.goto("/");
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByRole("heading", { name: "Identidad local de desarrollo" })).toBeVisible();
  await page.getByLabel("Identificador de prueba").fill(who);
  if (lifetime) await page.getByLabel("Duración de la sesión en segundos").fill(String(lifetime));
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.waitForURL(/\/(alta|inicio)$/);
}

export async function completeOnboarding(page: Page, goal = "Fondo para mudanza") {
  await expect(page.getByRole("heading", { level: 1, name: "Armemos tu plan" })).toBeVisible();
  await page.getByLabel("Moneda principal").selectOption("ARS");
  await page.getByLabel(/Ingreso mensual neto/).fill("1.800.000");
  await page.getByLabel(/Gasto mensual/).fill("1250000");
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByLabel(/Saldo disponible hoy/).fill("4.200.000");
  await page.getByRole("button", { name: "Continuar" }).click();
  await page.getByLabel("Nombre de la meta").fill(goal);
  await page.getByLabel(/Monto objetivo/).fill("1500000");
  await page.getByLabel("Plazo en meses").fill("10");
  await page.getByRole("button", { name: "Crear mi plan" }).click();
  await page.waitForURL(/\/inicio$/);
  await expect(page.getByRole("heading", { level: 1, name: "Tu situación" })).toBeVisible();
}

export async function goTo(page: Page, name: string) {
  const nav = page.getByRole("navigation", { name: "Secciones" });
  await nav.getByRole("link", { name }).click();
}

/** Captura de QA con datos ficticios, guardada en el directorio de resultados de Playwright. */
export async function snap(page: Page, info: TestInfo, name: string) {
  await page.screenshot({ path: info.outputPath(`${name}.png`), fullPage: true });
}

export async function storageIsClean(page: Page) {
  const keys = await page.evaluate(() => Object.keys(window.localStorage));
  expect(keys).toEqual([]);
}
