const EUR = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

/** Cents as German-formatted euros: 123456 -> "1.234,56 €". */
export function eur(cents: number | null | undefined): string {
  if (cents === null || cents === undefined) return "–";
  return EUR.format(cents / 100);
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return `${(v * 100).toFixed(digits)} %`;
}

const ISSUE_NAMES: Record<string, string> = {
  duplicate: "Possible duplicate",
  iban_changed: "Bank details changed",
  vat_rate_wrong: "Unusual VAT rate",
  reverse_charge_missing: "VAT charged where reverse charge applies",
  arithmetic: "Totals do not add up",
};

export function issueName(issue: string): string {
  return ISSUE_NAMES[issue] ?? issue;
}
