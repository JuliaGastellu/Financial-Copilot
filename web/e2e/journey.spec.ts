import { expect, test } from "@playwright/test";
import { completeOnboarding, goTo, signIn, snap, storageIsClean, subject } from "./helpers";

test("alta → plan → escenario → adopción → avance mensual", async ({ page }, info) => {
  await signIn(page, subject("recorrido"));
  await completeOnboarding(page);

  // Situación: próxima acción, presupuesto y motivos con montos y moneda.
  await expect(page.getByText("Próxima acción")).toBeVisible();
  await expect(page.getByRole("heading", { name: /Aportá ARS/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Presupuesto de este mes" })).toBeVisible();
  await expect(page.getByText("Disponible para repartir")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/probabilidad|confianza|catálogo/i);
  await snap(page, info, "01-situacion");

  // Plan mensual: versión 1.
  await goTo(page, "Plan mensual");
  await expect(page.getByText(/Versión 1, calculada/)).toBeVisible();
  await expect(page.getByRole("table", { name: "Reparto por meta" })).toContainText("Fondo para mudanza");

  // Escenario: caída de ingreso de 20%; el plan vigente no cambia.
  await goTo(page, "Escenarios");
  await page.getByLabel("Cambio de ingreso (%)").fill("-20");
  await page.getByRole("button", { name: "Simular" }).click();
  await expect(page.getByRole("table", { name: "Comparación por moneda" })).toBeVisible();
  await snap(page, info, "02-escenario");
  await goTo(page, "Plan mensual");
  await expect(page.getByText(/Versión 1, calculada/)).toBeVisible();

  // Adopción explícita con confirmación.
  await goTo(page, "Escenarios");
  await page.getByRole("button", { name: "Ingreso 20% menor" }).click();
  await page.getByRole("button", { name: "Adoptar este escenario" }).click();
  const dialog = page.getByRole("dialog", { name: "¿Adoptar este escenario?" });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Adoptar" }).click();
  await expect(page.getByText("Adoptaste el escenario")).toBeVisible();
  await goTo(page, "Plan mensual");
  await expect(page.getByText(/Versión 2, calculada/)).toBeVisible();
  const history = page.getByRole("region", { name: "Historial de versiones" }).or(page.locator("section", { hasText: "Historial de versiones" }));
  await expect(history).toContainText("Escenario adoptado");
  await expect(history).toContainText("Versión 1");

  // Revisión mensual: registro un aporte y veo el estado.
  await goTo(page, "Revisión mensual");
  await expect(page.getByRole("table", { name: /frente al plan/ })).toBeVisible();
  await page.getByLabel("Meta").selectOption({ label: "Fondo para mudanza" });
  await page.getByLabel("Monto aportado").fill("50.000");
  await page.getByRole("button", { name: "Registrar aporte" }).click();
  await expect(page.getByText("Registramos el aporte.")).toBeVisible();
  await expect(page.getByRole("table", { name: /frente al plan/ })).toContainText(/Parcial|Cumplido|Aporte adicional/);
  await expect(page.getByText("Tu plan está desactualizado")).toBeVisible();
  await snap(page, info, "03-revision");

  // Cómo lo calculé: fórmulas, supuestos, fechas y límites.
  await goTo(page, "Cómo lo calculé");
  await expect(page.getByRole("heading", { name: "Fórmulas" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Supuestos" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Límites" })).toBeVisible();

  // No guardo perfiles ni credenciales en localStorage.
  await storageIsClean(page);
});

test("un plan desactualizado se puede recalcular desde la situación", async ({ page }) => {
  await signIn(page, subject("desactualizado"));
  await completeOnboarding(page);
  await goTo(page, "Metas");
  await page.getByRole("button", { name: "Agregar una meta" }).click();
  await page.getByLabel("Nombre").fill("Curso de idioma");
  await page.getByLabel(/Monto objetivo/).fill("600000");
  await page.getByRole("button", { name: "Guardar meta" }).click();
  await expect(page.getByText(/Guardamos la meta/)).toBeVisible();
  await goTo(page, "Situación");
  await expect(page.getByText("Tu plan está desactualizado")).toBeVisible();
  await page.getByRole("button", { name: "Recalcular plan" }).click();
  await expect(page.getByText("Tu plan está desactualizado")).toHaveCount(0);
});

test("la demo está identificada y no requiere cuenta", async ({ page }, info) => {
  await page.goto("/");
  await page.getByRole("link", { name: /Ver una demo/ }).click();
  await expect(page.getByText("Estás viendo una demo con datos ficticios")).toBeVisible();
  await expect(page.getByRole("button", { name: /Adoptar|Registrar|Guardar/ })).toHaveCount(0);
  await snap(page, info, "04-demo");
});
