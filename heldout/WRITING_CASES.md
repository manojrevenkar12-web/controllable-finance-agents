# Writing a held-out case set

A held-out set tests the close agent and the pre-payment checks on cases written by someone who has **not read the
code**. Read only `docs/AGENT_BEHAVIOUR.md` and this file. Do not open `cfa/`, `tests/`, `config/`, `prompts/`,
`reports/` or other sets in `heldout/`.

Write `heldout/<set>/cases.yaml`: a list of cases, each self-contained (invent suppliers, amounts and notes; vary
the wording the way real German and English invoices do). Expected values follow from AGENT_BEHAVIOUR.md alone;
compute every amount to the cent and show the arithmetic in `why`.

## Close cases

```yaml
- id: close-01
  kind: close
  month: "2026-11"
  materiality_cents: 50000
  documents:                 # invoices of the month, with how their lines were booked
    - id: inv-1
      supplier_id: s-1
      supplier_name: Formfeld Software GmbH
      date: "2026-11-13"
      net_total: 365000
      notes: "Leistungszeitraum: 13.11.2026 – 12.11.2027"
      lines: [{net: 365000}]
      coding: [{account: "6837", cost_centre: "4000"}]
  history:                   # earlier invoices of the company (only what accruals need)
    - {id: h-1, supplier_id: s-2, supplier_name: Funknetz Mitte AG, month: "2026-08", date: "2026-08-03",
       net_total: 30000, notes: "Leistungszeitraum 08/2026", coding: [{account: "6805", cost_centre: "4000"}]}
  duplicates: []             # documents the checks found to be duplicates (optional)
  expect:
    entries:
      - {type: deferral, document_id: inv-1, debit: "1900", credit: "6837", amount_cents: 347000, cost_centre: "4000"}
      - {type: accrual, supplier_id: s-2, debit: "6805", credit: "3070", amount_cents: 33000, cost_centre: "4000"}
  why: "…"
```

The agent's entries for the case must equal `expect.entries` exactly (as a set; amounts to the cent).

## Check cases

```yaml
- id: check-01
  kind: check
  document:                  # the invoice to check
    {id: inv-9, kind: invoice, supplier_id: s-1, supplier_country: DE, number: "RE-2026-0412", date: "2026-11-20",
     iban: "DE…", lines: [{description: "Toner", net: 1000, vat_rate: 0.19, vat: 190}],
     net_total: 1000, vat_total: 190, gross_total: 1190}
  same_month: []             # other invoices of the same month (same shape)
  history: []                # earlier invoices of the company (same shape)
  booked_lines:              # earlier booked lines: what VAT the company paid for what
    - {supplier_id: s-1, supplier_country: DE, description: "Toner", vat_rate: 0.19}
  suppliers:                 # the supplier master: account on file and verified changes
    s-1: {iban: "DE…", bank_changes: [{old_iban: "DE…", new_iban: "DE…", verified_at: "2026-10-01"}]}
  expect: {issues: [duplicate]}   # the set of issues raised for the document; [] for a clean invoice
  why: "…"
```

Write 40 to 60 cases, about half close and half check. Cover: periods written in many ways (and notes that only
look like periods), mid-month starts, leap years, materiality exactly at the threshold, invoices with lines on two
accounts, duplicates skipped by the close, accruals with one missing month, with varying amounts, with ended
contracts phrased in new ways, suppliers that bill irregularly; every check issue, clean invoices that look
suspicious (verified bank changes, same-amount subscriptions, mixed VAT rates that are normal, reverse-charge
invoices done right), and invoices with more than one issue. Where AGENT_BEHAVIOUR.md leaves a case open, say so in
`why` and choose what a careful reader of it would expect.

Also write `heldout/<set>/README.md` (who wrote it, from what, and every ambiguity you found) and
`heldout/<set>/STATUS` containing `blind`.

## The rule

A set is run once; its first run is kept in `reports/heldout/<set>/first_run.json` and never rewritten. Nobody
changes the agents to pass a set before that. Studying its failures makes it a `regression` set, and a new blind set
is written by someone else from this file only.
