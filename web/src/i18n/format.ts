// Formato y lectura de importes. Solo convierto texto; no hago cálculos financieros en el navegador.
import type { Money } from "../api/types";

const LOCALE = "es-AR";

export function formatMoney(money: Money | null | undefined): string {
  if (!money) return "—";
  const value = Number(money.amount);
  if (!Number.isFinite(value)) return "—";
  try {
    return new Intl.NumberFormat(LOCALE, { style: "currency", currency: money.currency, currencyDisplay: "code" }).format(value);
  } catch {
    return `${money.currency} ${money.amount}`;
  }
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = value.length === 10 ? new Date(`${value}T12:00:00`) : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "long", year: "numeric" }).format(date);
}

export function formatMonth(period: string): string {
  const [year, month] = period.split("-").map(Number);
  if (!year || !month) return period;
  const text = new Intl.DateTimeFormat(LOCALE, { month: "long", year: "numeric" }).format(new Date(year, month - 1, 15));
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function currentPeriod(today: Date = new Date()): string {
  return `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * Leo un importe escrito por la persona y devuelvo una cadena decimal con punto,
 * o null si no es un número válido. Acepto «1.800.000,50», «1800000.5» y «1800000».
 */
export function parseAmount(input: string): string | null {
  const raw = input.trim().replace(/\s/g, "").replace(/^\$/, "");
  if (!raw) return null;
  let normalized: string;
  if (raw.includes(",") && raw.includes(".")) {
    normalized = raw.replace(/\./g, "").replace(",", ".");
  } else if (raw.includes(",")) {
    normalized = raw.replace(",", ".");
  } else if (/^\d{1,3}(\.\d{3})+$/.test(raw)) {
    normalized = raw.replace(/\./g, "");
  } else {
    normalized = raw;
  }
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null;
  return normalized.replace(/^0+(?=\d)/, "");
}

/** Convierto un porcentaje escrito («-20», «7,5») a la fracción que espera la API («-0.2000»). */
export function percentToFraction(input: string): string | null {
  const raw = input.trim().replace(",", ".");
  if (!/^-?\d+(\.\d{1,2})?$/.test(raw)) return null;
  const negative = raw.startsWith("-");
  const [whole, decimals = ""] = raw.replace("-", "").split(".");
  const digits = (whole + decimals.padEnd(2, "0")).replace(/^0+(?=\d)/, "");
  const padded = digits.padStart(5, "0");
  const fraction = `${padded.slice(0, -4)}.${padded.slice(-4)}`.replace(/^0+(?=\d)/, "");
  return `${negative && Number(fraction) !== 0 ? "-" : ""}${fraction}`;
}

export function fractionToPercent(value: string): string {
  const n = Number(value) * 100;
  return `${n > 0 ? "+" : ""}${new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 2 }).format(n)} %`;
}
