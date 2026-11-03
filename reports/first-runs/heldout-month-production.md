# Release decision: production

On the `heldout` split (670 documents). **Do not ship.** Failed: close.accrual_recall.

| Gate | Value | Limit | Result |
|---|---|---|---|
| coding.precision_ready | 0.985 | ≥ 0.98 | pass |
| coding.coverage_ready | 0.607 | ≥ 0.3 | pass |
| coding.document_accuracy | 0.966 | ≥ 0.9 | pass |
| checks.recall | 0.956 | ≥ 0.9 | pass |
| checks.precision | 1.000 | ≥ 0.9 | pass |
| checks.decoy_false_alarms | 0 | ≤ 0 | pass |
| close.deferral_recall | 1.000 | ≥ 0.9 | pass |
| close.accrual_recall | 0.875 | ≥ 0.9 | fail |
| close.precision | 1.000 | ≥ 0.95 | pass |
| close.cancelled_accrued | 0 | ≤ 0 | pass |

Model calls 51, cost $0.0440, p95 3296 ms per document.

Run once, at the end, after test had been studied; nothing was changed because of it.
