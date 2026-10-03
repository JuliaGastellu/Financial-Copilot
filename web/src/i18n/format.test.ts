import { describe, expect, test } from "vitest";
import { formatMoney, fractionToPercent, parseAmount, percentToFraction } from "./format";

describe("parseAmount", () => {
  test.each([
    ["1800000", "1800000"],
    ["1.800.000", "1800000"],
    ["1.800.000,50", "1800000.50"],
    ["1800000,5", "1800000.5"],
    ["1800000.25", "1800000.25"],
    ["$ 2.500", "2500"],
    ["0", "0"],
    ["007", "7"],
  ])("%s → %s", (input, expected) => expect(parseAmount(input)).toBe(expected));

  test.each(["", "abc", "1,2,3", "-5", "1.5.5", "1e6", "12,345", "NaN", "Infinity"])("rechaza %s", (input) => {
    expect(parseAmount(input)).toBeNull();
  });
});

describe("percentToFraction", () => {
  test.each([
    ["-20", "-0.2000"],
    ["7,5", "0.0750"],
    ["150", "1.5000"],
    ["0", "0.0000"],
    ["-0", "0.0000"],
  ])("%s → %s", (input, expected) => expect(percentToFraction(input)).toBe(expected));

  test("rechaza texto", () => expect(percentToFraction("veinte")).toBeNull());
});

test("formatMoney muestra la moneda y distingue la ausencia de dato", () => {
  expect(formatMoney({ amount: "2500.00", currency: "USD" })).toMatch(/USD/);
  expect(formatMoney({ amount: "2500.00", currency: "USD" })).toMatch(/2\.500,00/);
  expect(formatMoney(null)).toBe("—");
  expect(fractionToPercent("-0.2000")).toMatch(/-20/);
});
