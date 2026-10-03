import { expect, test } from "@playwright/test";
import { completeOnboarding, goTo, signIn, subject } from "./helpers";

test("otra cuenta no ve los datos de la anterior", async ({ page }) => {
  await signIn(page, subject("alicia"));
  await completeOnboarding(page, "Meta privada de Alicia");
  await goTo(page, "Cuenta");
  await page.getByRole("button", { name: "Cerrar sesión" }).click();
  await page.waitForURL((url) => url.pathname === "/");

  await signIn(page, subject("bruno"));
  await expect(page).toHaveURL(/\/alta$/);
  await expect(page.locator("body")).not.toContainText("Meta privada de Alicia");
});

test("al recargar no queda una sesión guardada en el navegador", async ({ page }) => {
  await signIn(page, subject("recarga"));
  await completeOnboarding(page);
  await page.reload();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("button", { name: "Iniciar sesión" })).toBeVisible();
});

test("sesión vencida: el formulario se conserva y se puede reintentar", async ({ page }) => {
  const who = subject("vence");
  const started = Date.now();
  await signIn(page, who, 25);
  await completeOnboarding(page);
  await goTo(page, "Metas");
  await page.getByRole("button", { name: "Agregar una meta" }).click();
  await page.getByLabel("Nombre").fill("Viaje corto");
  await page.getByLabel(/Monto objetivo/).fill("300000");
  // Espero a que venza el token de 25 segundos antes de guardar.
  await page.waitForTimeout(Math.max(0, 27_000 - (Date.now() - started)));
  await page.getByRole("button", { name: "Guardar meta" }).click();
  await expect(page.getByText("Tu sesión venció")).toBeVisible();
  await expect(page.getByLabel("Nombre")).toHaveValue("Viaje corto");

  const popupPromise = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Iniciar sesión de nuevo" }).click();
  const popup = await popupPromise;
  await popup.getByLabel("Identificador de prueba").fill(who);
  await popup.getByRole("button", { name: "Continuar" }).click();
  await expect(page.getByText("Tu sesión venció")).toHaveCount(0);
  await page.getByRole("button", { name: "Guardar meta" }).click();
  await expect(page.getByText(/Guardamos la meta/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Viaje corto" })).toBeVisible();
});
