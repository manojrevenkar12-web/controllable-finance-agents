# Held-out set `blind-2`

## Who wrote it, and from what

Written on 2026-11-03 by a Claude subagent that had **not seen the code**. It read exactly two files:

- `heldout/WRITING_CASES.md` (format and coverage)
- `docs/AGENT_BEHAVIOUR.md` (the contract)

It did not open, list or search `cfa/`, `tests/`, `config/`, `prompts/`, `reports/`, `fixtures/`, `data/`, `web/`,
`infra/` or any other set under `heldout/`, and it ran no project command (no `cfa`, no pytest). Python was used only
for arithmetic (day counts, rounding, coefficients of variation, IBAN mod-97 check digits) and to check that
`cases.yaml` parses and that every invoice's arithmetic matches the expected `arithmetic` findings.

All companies, suppliers, invoice numbers and IBANs are invented. Every IBAN has valid ISO 13616 check digits (the
French one also has a valid RIB key, the Dutch one passes the 11-test). Amounts are integer cents, rounded half away
from zero; every `why` shows the arithmetic.

## What the cases cover

60 cases: 30 `close`, 30 `check`.

### Close (30)

| Area | Cases |
| --- | --- |
| German periods: `vom … bis …`, `bis einschl.`, two-digit years, written-out German months | close-01, -04, -05, -19 |
| English periods: `through`, ordinals (`1st February … to 31st January`), abbreviated months, British `dd/mm/yyyy` | close-02, -06, -13, -19 |
| ISO dates joined by German `bis`; ISO dates that are not a period (`Order … / Delivery …`) | close-30, -15 |
| Start and a length: months (German and English), 24 months across a leap year, days | close-03, -09, -17 |
| Invoice of the month for a period that began months earlier | close-03 |
| Period ending exactly on the month end (no entry) / one day after / starting the day after | close-04, -07, -08, -09 |
| Leap years: February 2028 close, period through 29.02.2028, period across 29.02.2028 | close-09, -10 |
| Months other than 2026-12 / 2027-01: 2027-02, 2027-03, 2027-06, 2027-12, 2028-02 | close-06, -28, -29, -10, -09 |
| Materiality exactly at, one cent below, tested on invoice total not per account | close-11, -12, -29 |
| Lines on two accounts; three lines on two accounts (same account summed); cost centre of first line | close-12, -13, -30 |
| Exact half cent rounding away from zero | close-18 |
| Duplicates skipped by the close | close-14, -30 |
| Notes that only look like periods (delivery + due date, price validity, booking + event, order + delivery) | close-15, -30 |
| Named year, named quarter, start without end, one month only | close-11, -16, -20, -30 |
| Accrual: plain monthly supplier; supplier that already billed this month | close-20, -30 |
| Accrual: one missing month (middle; latest), with account/cost centre taken from the latest invoice | close-21, -22 |
| Irregular billers: two invoices in one month, quarterly, one of three months | close-23 |
| Coefficient of variation 0.24938 vs 0.25092 | close-24 |
| Day-of-month spread exactly 10 vs 11 | close-25 |
| Contract ends in new wordings (final bill, plan closed, contract expired, lease end, Abschlussrechnung, final invoice) | close-26, -28, -30 |
| Not an end: notice period, automatic renewal unless cancelled, price change with right to cancel, withdrawn cancellation on an older invoice | close-27, -28 |
| Accrual for a supplier below materiality next to a deferral stopped by materiality | close-29 |

### Check (30)

| Issue / trap | Cases |
| --- | --- |
| Clean invoice; same number from a different supplier | check-01 |
| `duplicate` by number with punctuation, spaces, case and leading zeros | check-02, -28 |
| Checked invoice is the original (later copy in the same month) → clean | check-03 |
| `duplicate` by same gross + same descriptions 6 days apart, different numbers | check-04 |
| Monthly subscription, same amount, different numbers → clean | check-05 |
| Weekly service, same amount 7 days apart, descriptions differ → clean | check-06 |
| "Corrected" invoice reusing a number with a different amount → `duplicate` | check-07 |
| `iban_changed`: new account used before verification; old account used after verification; unknown account | check-08, -11, -13 |
| Bank change verified on the invoice date / before it; two-step chain, invoice between the steps → clean | check-09, -10, -12 |
| `vat_rate_wrong`: known item at a rate never paid; never-bought item vs. a German supplier's single rate; German supplier at 0 % | check-14, -16, -19 |
| Rate paid once before among several → clean; never-bought item from a mixed-rate supplier → clean | check-15, -17 |
| Normal mixed 7 % / 19 % invoice → clean | check-18 |
| Reverse charge done right (AT; IE for an item German suppliers charge 19 % on) → clean | check-20, -21 |
| `reverse_charge_missing`: NL charging German VAT, FR charging French VAT | check-22, -23 |
| `arithmetic`: line VAT off; lines not adding to the net total; net + VAT ≠ gross | check-24, -26, -27 |
| One-cent rounding difference on a line → clean | check-25 |
| Several issues: duplicate + iban_changed; reverse_charge_missing + arithmetic; vat_rate_wrong + arithmetic | check-28, -29, -30 |

## Ambiguities found in AGENT_BEHAVIOUR.md and how they were resolved

1. **Format of `duplicates` in a close case.** WRITING_CASES.md shows only `duplicates: []`. Resolved: a list of
   document ids of the month (`[inv-2]`).
2. **Pairing of `lines` and `coding`.** Not stated. Resolved: `coding[i]` is the booking of `lines[i]`; every
   document here has one coding entry per line.
3. **The accrual example in WRITING_CASES.md is not consistent with the contract** (one history invoice of
   30000 three months back, expected accrual 33000). Treated as an illustration of the format only; this set
   follows AGENT_BEHAVIOUR.md.
4. **Cost centre when lines sit on different cost centres.** The contract says "that of the invoice's first
   line" for every entry; followed literally (close-12, -13, -30), even where an accountant might split by line.
5. **Start and a length given in days** (`90 Tage ab dem 01.01.2027`). The contract only shows months. Resolved by
   the same convention as its example (the start day is day 1, so the end is start + length − 1 day): 01.01.–31.03.2027
   (close-17). Lengths that land on a non-existent day (31 January + 1 month, 29 February + 12 months) were avoided.
6. **Months without days** (`Dezember 2026 bis Februar 2027`, `01/2027 – 12/2027`). The contract requires a first
   and a last *day*; unclear whether such ranges count. Avoided.
7. **Slash dates** (`01/12/2026`) are ambiguous between day/month and month/day. Only one used, where both day
   numbers exceed 12 (`15/12/2026 - 14/06/2027`, close-19), so it is decidable.
8. **Notes with two dates that are not a service period** (delivery + due date, price validity, order + delivery,
   booking + event). The contract says only "a service period" and "never guesses dates". Resolved: no deferral
   (close-15, close-30 inv-4); `why` says so.
9. **Whether materiality applies to accruals.** It is listed only under deferrals. Resolved: accruals have no
   materiality test (close-29). A reader who applies it to accruals would expect no entry there.
10. **Leading zeros in invoice numbers.** "Leading zeros" could mean of the whole number or of each digit group.
    The contract's own example (`RE-2026-0412` = `re2026/412`) only works per digit group, so that reading is used
    (check-02).
11. **"Within 14 days" at exactly 14 days.** Inclusive or not is unstated. Avoided: duplicates-by-amount cases are
    6, 7 and 31 days apart; check-28 is exactly 14 days apart but is also a duplicate by number, so it does not
    depend on it.
12. **"Same line descriptions"**: exact text or normalised, list or set. Avoided: descriptions are either
    identical or clearly different (KW 49 vs KW 50).
13. **Which lines the VAT-rate rule applies to, and what counts as the basis.** The basis is "earlier lines of
    it from German suppliers". Resolved: (a) lines from foreign suppliers never count towards the basis, so a
    German supplier at 0 % for an item German suppliers charged 19 % is `vat_rate_wrong` even though the company
    has 0 % lines for that item from an Irish supplier (check-19); (b) the rule is applied to German suppliers'
    lines only, so an EU supplier's correct 0 % reverse-charge line is not `vat_rate_wrong` (check-21; WRITING_CASES
    lists "reverse-charge invoices done right" as clean). A literal reader could flag check-21 and spare check-19.
14. **Item seen fewer than three times.** Neither the three-line rule nor the never-bought fallback applies to an
    item bought once or twice. Avoided.
15. **Non-EU suppliers charging VAT** (e.g. Swiss VAT). Not covered by `reverse_charge_missing` as written.
    Avoided.
16. **IBAN formatting** (spaces, lower case) as a difference of account. Avoided: all IBANs are compact upper case.
17. **Arithmetic tolerance on totals.** One cent is allowed per line; the contract gives no tolerance for
    "the lines do not add up to the totals" (common when VAT is computed on the total per rate). Avoided: every
    total in this set either matches exactly or is off by 100 cents or more.
18. **Day-of-month spread across a month end** (invoices dated 30th, 1st, 2nd are close in time but 29 apart as
    day numbers). The contract says "days of the month", which suggests the number literally. Avoided.
19. **A supplier with fewer than three invoices in total.** "The average of the three latest invoices" is undefined.
    Avoided: every accrual candidate has at least three invoices.
20. **A future contract end on the latest invoice** ("Kündigung bestätigt zum 31.03.2027" while service continues).
    "Says the contract ends" could include a future end date. Avoided; close-28 uses a cancellation that was
    later withdrawn, on an older invoice, which the "latest invoice" rule decides.
21. **Accrual for a supplier that skipped last month** (billed M-3 and M-2, not M-1). The contract's "at least
    two of the three" admits it; followed (close-22), and only the current month is accrued.
22. **An account of the latest invoice with lines on several accounts.** Undefined for accruals. Avoided: every
    history invoice has one coding entry.
23. **Named periods an accountant would defer** (`Q1/2027` billed in December, `Jahreslizenz 2027`). The contract
    excludes them explicitly; followed (close-16), noting it is narrower than practice.
