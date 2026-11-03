import { eur, issueName, pct } from "./money";

test("euros from cents, German style", () => {
  expect(eur(123456).replace(/\s/g, " ")).toBe("1.234,56 €");
  expect(eur(-5).replace(/\s/g, " ")).toBe("-0,05 €");
  expect(eur(null)).toBe("–");
});

test("percentages", () => {
  expect(pct(0.985, 1)).toBe("98.5 %");
  expect(pct(undefined)).toBe("–");
});

test("issues read as words", () => {
  expect(issueName("iban_changed")).toBe("Bank details changed");
  expect(issueName("new_kind")).toBe("new_kind");
});
