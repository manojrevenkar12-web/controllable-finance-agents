# Held-out set blind-1

Author: written by a Claude subagent that had not seen the code, from docs/AGENT_BEHAVIOUR.md and
heldout/WRITING_CASES.md only. No file under `cfa/`, `tests/`, `config/`, `prompts/`, `reports/`, `fixtures/`,
`data/`, `web/`, `infra/` or any other `heldout/` set was opened. Python was used only for arithmetic (day counts,
rounding, coefficients of variation, IBAN check digits) and to load the YAML.

Status: `blind` (see `STATUS`). Run it once; the first run is kept and never rewritten.

## Contents

57 cases: 28 `close`, 29 `check`. Every amount is in integer cents. Period days are counted inclusively, and amounts
are rounded half away from zero. Each case's `why` shows the arithmetic.

Close (28):

| Topic | Cases |
|---|---|
| German dates (`–`, `vom … bis …`, `bis einschließlich`, two-digit years) | 01, 02, 24, 25, 28 |
| English dates (`Nov 1, 2026 to …`, `15 Nov 2026 – …`, `December 1, 2026 through …`) | 03, 15, 27 |
| ISO dates | 04 |
| Start plus length (German and English) | 05, 06 |
| Mid-month starts | 01, 05, 11, 15, 28 |
| Periods that start after the month or before it | 02, 09 |
| Leap years (period over 29.02.2028, month ending 29.02.2028, exact half cent) | 06, 11, 12 |
| Notes that only look like periods (single month, payment or offer dates, year or quarter only, start with no end, period ending on or before month end) | 07, 08, 09, 10 |
| Materiality exactly at the threshold, one cent below it, and below it | 13, 24 |
| Lines on two accounts (cost centre from the first line, A-B-A line order) | 14, 15 |
| Duplicate skipped by the close | 16 |
| Accrual basics, and a supplier that already billed this month | 17 |
| Accrual with one missing month | 18 |
| Varying amounts on both sides of CV 0.25 | 19 |
| Day spread exactly 10 vs 11 | 20 |
| Ended contracts phrased in new ways | 21 |
| Notes that mention termination without ending the contract | 22 |
| Irregular billers (two in one month, one of three months, quarterly) | 23 |
| Accrual below materiality, close across a year end and across a year boundary | 24, 25 |
| Day-of-month wrap | 26 |

Check (29): the expected issues are

| Expected | Cases |
|---|---|
| `duplicate` | 02 (number formatting), 03 (leading zeros, same month), 04 (same gross and description within 11 days) |
| `iban_changed` | 08 (unknown account), 10 (new account used before verification), 11 (old account after verification) |
| `vat_rate_wrong` | 13 (item rule), 16 (never-bought item, single-rate supplier) |
| `reverse_charge_missing` | 19 |
| `arithmetic` | 22 (line VAT), 24 (lines vs total), 25 (net + VAT vs gross) |
| more than one issue | 26 (duplicate + iban_changed), 27 (reverse_charge_missing + arithmetic), 28 (vat_rate_wrong + iban_changed) |
| clean, but looks suspicious | 01, 05 (same-amount monthly subscription), 06 (the original of a later duplicate), 07 (same number, other supplier), 09 (verified change), 12 (verified on the invoice date), 14 (normal mixed rates), 15 (item paid at two rates), 17 (new item, mixed-rate supplier), 18 (too few German lines), 20 (reverse charge done right), 21 (non-EU, no VAT), 23 (VAT off by ≤ 1 cent), 29 (weekly same-amount invoices) |

German IBANs are invented, 22 characters long, with valid mod-97 check digits. The foreign IBANs (AT, NL, FR, CH)
are invented in their country formats.

## Ambiguities found in AGENT_BEHAVIOUR.md and how this set resolves them

1. **What counts as a stated period.** The contract lists formats that count and says a single month does not. It
   does not say what to do with:
   - a named year or quarter (`Jahreslizenz 2027`, `Q1/2027`),
   - a start date with no end (`ab 01.12.2026`),
   - a month range (`11/2026 – 10/2027`),
   - two dates that are not a service period (payment terms, offer validity).

   Because the contract says "first and last day" and "never guesses", close-08 and close-10 expect no deferral.
   No case uses a month range. An accountant would usually defer a named year or quarter, so close-10 tests the
   literal contract.
2. **Two-digit years** (`15.11.26 - 14.02.27`) are not among the listed formats. close-28 treats them as clear
   (2026/2027).
3. **Start plus length when the start day does not exist in the end month** (for example `3 Monate ab 31.01.`).
   The contract's example only shows "same day next year minus one". No case depends on this.
   close-05 and close-06 use "start + N months − 1 day", as in the contract's example.
4. **Days after the month for a period that starts after the month.** The formula gives all days of the period,
   so the whole net is deferred (close-02). The contract does not say this outright.
5. **Materiality for accruals.** Materiality is stated only for deferrals. close-24 expects an accrual of 4247
   below a 50000 threshold. The other accrual cases set the threshold low, so they do not depend on this.
6. **"Three latest invoices" when a supplier has fewer than three.** The contract allows billing in two of three
   months, but averages "the three latest invoices". Every accrual supplier in this set has at least three invoices
   in its history. A supplier with only two invoices is undefined.
7. **Day-of-month spread across a month end.** Taken literally, invoices on 30.07., 01.09. and 01.10. are 29 days
   apart, so there is no accrual (close-26), even though the supplier is effectively monthly.
8. **Account and cost centre of the latest invoice when it has several lines or accounts.** The contract says
   "the account of the supplier's latest invoice". All history invoices here have a single coding entry.
9. **Ending phrases.** Only examples are given. close-21 treats new phrasings of an end as ending. close-22
   treats a notice period and an automatic renewal "unless terminated" as not ending.
10. **Whether a supplier whose only this-month invoice is a duplicate has "already billed this month".** No case
    depends on this.
11. **Duplicate number normalisation.** "Leading zeros" is read as leading zeros of each digit group
    (`RE-2026-0412` = `re2026/412`, as in the contract's example; `INV-000731` = `inv 731`).
12. **"Within 14 days".** The contract does not say whether exactly 14 days counts. No case sits on the boundary:
    check-04 is 11 days apart and check-05 is 31 days apart. check-29 has an invoice exactly 14 days earlier, but
    its descriptions differ, so the boundary does not matter there.
13. **"Same line descriptions".** The contract does not say how strictly descriptions compare. check-29 reads it as
    the same text: weekly invoices that differ only in the calendar week (`KW 45` vs `KW 46`) are not duplicates.
    Under the same rule, identical weekly invoices less than 14 days apart *would* be duplicates. A real accountant
    might disagree, so no case tests it.
14. **An invoice on the same date as an earlier one with the same number.** Which one is "earlier" is undefined.
    No case depends on this.
15. **Supplier master `iban`.** This set reads it as the current account after all changes, including a change
    verified after the invoice date (check-10, check-28). For an earlier invoice date, the `old_iban` of a later
    change is the account on file.
16. **IBAN formatting** (spaces, case). The contract does not say whether `DE02 1005 …` equals `DE021005…`. All
    IBANs here are written without spaces.
17. **The rate check and the other rules interact:**
    - The contract does not say whether `vat_rate_wrong` applies to non-German suppliers. check-20 expects a correct
      reverse-charge invoice (0 %) to get no finding, even though earlier German lines of the same item were at
      19 %, because "a correct invoice gets no finding". The reverse-charge cases (check-19, check-27) use items and
      suppliers with no booked history, so they do not depend on this.
    - The contract does not say whether lines from non-German suppliers count towards "never paid". check-18 counts
      only German lines, as the contract says.
18. **Items with one or two earlier German lines.** The item rule needs three lines, and the never-bought rule only
    applies to items never bought. So an item bought once or twice cannot be judged, whatever its supplier's
    history (check-16 `Kabelkanal`, check-18). check-18 expects no finding even though 19 % on a book looks wrong.
19. **"A German supplier that has charged a single rate on at least three earlier lines".** This set reads it as
    the invoice's own supplier, over all its earlier lines and all items (check-16, check-17).
20. **Whether invoice lines in `history` count as booked lines for the rate check.** Every case keeps the two
    consistent, so this does not matter here.
21. **One-cent tolerance with floating-point rates.** check-23 has a line VAT exactly 1.00 cent from net × rate
    (2000 × 0.19 = 380 vs 381). In IEEE doubles 2000 × 0.19 is exactly 380.0, so float and decimal give the same
    answer.
22. **Which EU countries count, and services vs goods.** All EU reverse-charge cases are services (consulting,
    hosting, translation). Switzerland is treated as non-EU (check-21).
