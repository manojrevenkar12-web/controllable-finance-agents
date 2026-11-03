# How the agents are evaluated, and what has been looked at

The numbers in the README come from the reports in `reports/`, which CI regenerates and compares
(`cfa release production` must reproduce `reports/releases/production.json` exactly, with model answers replayed
from `fixtures/llm_cache/`). This page says where each number comes from and which data has been studied.
Numbers measured on studied data are labelled as such.

## The data

The companies, suppliers, people and invoices are synthetic. `cfa/sim` generates them from `config/world.yaml`:

- 10 companies, each with its own booking habits and materiality threshold;
- 30 suppliers, including recurring ones (rent, telecoms, SaaS) and ones that appear partway through the year;
- 12 months of history (November 2025 to October 2026), booked with deliberate noise: 3 % of history lines
  miscoded, SKU-style item descriptions, cost-centre notes that override the requester's department, and habits
  that change partway through the year.

Three evaluation months follow the history. Each has documents, the bookings an accountant would make, planted
payment issues, decoys (verified bank changes, same-amount subscriptions) and the close entries an accountant
would propose.

| Split | Month | Documents | Used for |
|---|---|---|---|
| dev | 2026-11 | 619 | everything: development, error analysis, calibration |
| test | 2026-12 | 663 | the release gates (`config/gates.yaml`) |
| heldout | 2027-01 | 670 | run once at the end |

The truth files (`data/<split>/truth.json`) are read only by `cfa/evals`. `tests/test_isolation.py` checks that
`cfa/agents` and the MCP server never import the simulator or the evals, and never name a truth file.

## Calibration

The coding agent's confidence is the Wilson lower bound of the share of earlier bookings that agree. Recent bookings
count more, with a half-life of 75 days. `cfa calibrate` picks the lowest confidence at which documents booked in
bulk on **dev** are right 99 times in 100. The result is 0.4494, with precision 0.991 on 467 dev documents.
It is written to `config/thresholds.yaml` with the split and date it was chosen on. Test is never used for this.

## What has been studied, in order

1. **dev**: everything was developed on it.
2. **test, first run** (`reports/first-runs/test-production.md`): did not ship. Accrual recall was 0.625. Every
   other gate passed. Reading the misses turned up two problems:
   - the agent required an invoice in each of the last three months. A real monthly supplier sometimes skips one;
   - a generator bug announced some cancellations on invoices that were never issued.

   Both were fixed. The data was regenerated and dev was recalibrated. **The test numbers in the README were
   measured on test after it had been studied.**
3. **heldout month, first and only run** (`reports/first-runs/heldout-month-production.md`): does **not** pass the
   gates. Accrual recall is 0.875: one of eight expected accruals was missed, which is below the 0.9 floor.
   Everything else passes:
   - coding: precision in bulk 0.985, coverage 0.607, document accuracy 0.966;
   - checks: recall 0.956, precision 1.000, no false alarms on decoys;
   - close: deferral recall 1.000, close precision 1.000.

   Nothing was changed because of this run.
4. **blind-1** (`heldout/blind-1`): 57 hand-written cases from an author who had not seen the code.
   - First run: 54 of 57, kept in `reports/heldout/blind-1/first_run.json`. All 29 checks passed.
   - Three close cases failed: the model supplied dates for "Jahreslizenz 2027" and "Q1/2027", and contract ends
     were matched by a fixed word list.
   - The failures were studied and the close agent changed (`heldout/blind-1/STUDIED.md`). The set is now a
     regression set: 57 of 57.
5. **blind-2** (`heldout/blind-2`): written after that change, by a new author who saw only
   `docs/AGENT_BEHAVIOUR.md` and `heldout/WRITING_CASES.md`. Its first run is in
   `reports/heldout/blind-2/first_run.json`: **53 of 60**. All 30 checks passed and 23 of 30 close cases passed.
   The close failures are in reading wordings the rules had not seen:
   - service periods written in new ways (missed deferrals, and one deferral that should not exist);
   - contract ends phrased in new ways ("plan has been closed", "Leasingende"), which led to accruals that should
     not exist;
   - a notice of a price change with a right to cancel, which led to a missed accrual.

   Nothing was changed for this set. Fixing the failures would make it a regression set and call for a third set.
   The likely change is structural, not a longer word list: let the model read the contract status, as it reads
   periods, and accept its answer only when it quotes the sentence it relied on.

## Release candidates

`config/variants.yaml` describes candidate versions as overrides of production. `cfa release <variant>` evaluates a
candidate on test and applies the gates:

| Candidate | Change | Decision on test | Failed gates |
|---|---|---|---|
| production | — | ships | — |
| no-recency | old bookings weigh as much as new ones | refused | coding.precision_ready (0.966) |
| ignore-notes | cost-centre notes on invoices are not read | refused | coding.precision_ready (0.917), document_accuracy (0.839) |
| iban-from-history | bank details compared with earlier invoices, not the verified master | refused | checks.precision (0.619), decoy_false_alarms |

CI checks that the three refused candidates are still refused.

## Limits

- The data is synthetic. It was built to be hard in ways the documented failure modes of finance automation are
  hard: habit changes, notes, verified bank changes, reverse charge and irregular billers. Still, it is not a
  customer's ledger, and the numbers do not predict a customer's numbers.
- The model is used only where the rules give no answer: lines with no booking pattern, and notes whose period
  the rules cannot read. On test it was called 34 times for 663 documents, for $0.035 in total. Its answers are
  cached in `fixtures/llm_cache/` so that runs reproduce exactly. The cost of a fresh run would differ.
