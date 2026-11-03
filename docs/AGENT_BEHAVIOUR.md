# What the agents should propose

This is the contract for the month-end close and the pre-payment checks: what a careful accountant expects the
agents to propose, from the documents alone. The held-out sets in `heldout/` are written from this page; the code
in `cfa/agents/` implements it.

Amounts are integer cents. "Net" is the amount before VAT. Rounding is commercial: half a cent and more rounds
away from zero.

## Month-end close

The close runs for one company and one month (`YYYY-MM`). It sees the month's documents (with the account and cost
centre each line was booked to), the company's earlier documents (with their bookings), and the company's
materiality threshold.

### Deferrals (prepaid expenses)

An invoice of the month whose notes state a **service period ending after the last day of the month** is partly an
expense of later months. The agent proposes one journal entry per expense account on the invoice:

- debit `1900` (aktive Rechnungsabgrenzung), credit the expense account the lines were booked to;
- amount = (net of that account's lines) × (days of the period after the month's last day) ÷ (days in the period),
  rounded to the cent. Both ends of the period count as days: 1 January to 31 December is 365 days;
- cost centre: that of the invoice's first line;
- only if the invoice's total net is **at least** the company's materiality threshold;
- not for an invoice the checks found to be a duplicate.

A period is stated when the notes give a first and a last day, in any of the ways suppliers write them: German
dates (`01.11.2026 – 31.10.2027`, `vom … bis …`), English (`Nov 1, 2026 to Oct 31, 2027`), ISO
(`2026-11-01 – 2027-10-31`), or a start and a length (`Laufzeit 12 Monate ab dem 15.11.2026`: 15.11.2026 to
14.11.2027). A note that names only one month (`Leistungszeitraum 11/2026`) states no period beyond the month.
A note that does not state a period clearly gets no deferral: the agent never guesses dates.

### Accruals (invoices not yet received)

A supplier that bills the company **once a month** but has not sent this month's invoice still delivered. The
agent proposes:

- debit the account of the supplier's latest invoice, credit `3070` (sonstige Rückstellungen);
- amount = the average net of the supplier's three latest invoices, rounded to the cent;
- cost centre: that of the latest invoice's first line.

A supplier bills once a month when, in the three months before this one, it sent exactly one invoice in each month
it billed, and billed in at least two of the three; and its three latest invoices have similar amounts (the
coefficient of variation of their nets, population standard deviation over mean, is at most 0.25) and dates (their
days of the month are at most 10 apart). No accrual is proposed when the supplier already
billed this month, or when its latest invoice says the contract ends (for example "Vertrag gekündigt", "letzte
Rechnung", "contract ends", "final invoice").

## Pre-payment checks

Each finding is one of five issues, raised for one document:

- `duplicate`: the same supplier sent an invoice with the same number before (numbers compare without punctuation,
  spaces, case and leading zeros: `RE-2026-0412`, `re2026/412` and `Re.-2026-412` are the same), or with the same
  gross amount and the same line descriptions within 14 days. The earlier invoice is the original; the later one is
  the duplicate.
- `iban_changed`: the invoice's bank account is not the supplier's account on file for the invoice date. A change
  of bank details counts from the day it was verified; before that day, the old account was the one on file.
- `vat_rate_wrong`: a line charges a VAT rate this company has never paid for that item (the item is the first word
  of the description), judged from at least three earlier lines of it from German suppliers. For an item never
  bought before, a German supplier that has charged a single rate on at least three earlier lines sets the
  expectation instead.
- `reverse_charge_missing`: a supplier from another EU country charges VAT (services from other EU countries fall
  under reverse charge, § 13b UStG).
- `arithmetic`: a line's VAT differs from net × rate by more than one cent, the lines do not add up to the totals,
  or net + VAT differs from gross.

A correct invoice gets no finding. In particular: a bank change verified before the invoice date is not a finding,
and two monthly invoices of a subscription with the same amount and different numbers are not duplicates.
