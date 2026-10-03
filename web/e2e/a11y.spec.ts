import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { completeOnboarding, goTo, signIn, subject } from "./helpers";

async function audit(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const summary = results.violations.map((v) => `${v.id} (${v.nodes.length}): ${v.help}`);
  expect(summary, `Violaciones de accesibilidad en ${label}`).toEqual([]);
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test("páginas públicas sin violaciones de accesibilidad", async ({ page }) => {
  await page.goto("/");
  await audit(page, "inicio");
  await noHorizontalScroll(page);
  await page.goto("/demo");
  await audit(page, "demo");
  await noHorizontalScroll(page);
});

test("páginas de la cuenta sin violaciones de accesibilidad", async ({ page }) => {
  await signIn(page, subject("a11y"));
  await audit(page, "alta paso 1");
  // Envío vacío: los errores quedan asociados a sus campos.
  await page.getByRole("button", { name: "Continuar" }).click();
  await expect(page.getByLabel(/Ingreso mensual neto/)).toHaveAttribute("aria-invalid", "true");
  await audit(page, "alta con errores");
  await page.reload();
  await signIn(page, subject("a11y"));
  await completeOnboarding(page);
  for (const [link, label] of [
    ["Situación", "situación"],
    ["Plan mensual", "plan"],
    ["Metas", "metas"],
    ["Escenarios", "escenarios"],
    ["Revisión mensual", "revisión"],
    ["Cómo lo calculé", "cómo lo calculé"],
    ["Cuenta", "cuenta"],
  ]) {
    await goTo(page, link);
    await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
    await audit(page, label);
    await noHorizontalScroll(page);
  }
});

test("el alta se completa solo con teclado y el foco es visible", async ({ page }) => {
  await signIn(page, subject("teclado"));
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Ir al contenido" })).toBeFocused();
  const outline = await page.evaluate(() => getComputedStyle(document.activeElement as Element).outlineStyle);
  expect(outline).not.toBe("none");

  await page.getByLabel(/Ingreso mensual neto/).focus();
  await page.keyboard.type("1800000");
  await page.keyboard.press("Tab");
  // Recorro las opciones de procedencia con flechas, como cualquier grupo de radio.
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("radio", { name: "Estimación" }).first()).toBeChecked();
  await page.getByLabel(/Gasto mensual/).focus();
  await page.keyboard.type("1250000");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Tu reserva" })).toBeVisible();
  await page.getByLabel(/Saldo disponible hoy/).focus();
  await page.keyboard.type("0");
  await page.keyboard.press("Enter");
  await page.getByLabel("Nombre de la meta").focus();
  await page.keyboard.type("Reserva para imprevistos");
  await page.keyboard.press("Tab");
  await page.keyboard.type("500000");
  await page.keyboard.press("Enter");
  await page.waitForURL(/\/inicio$/);
  await expect(page.getByRole("heading", { level: 1, name: "Tu situación" })).toBeFocused();
});
