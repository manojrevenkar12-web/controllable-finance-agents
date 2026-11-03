# Release decision: no-recency

On the `test` split (663 documents). **Do not ship.** Failed: coding.precision_ready.

| Gate | Value | Limit | Result |
|---|---|---|---|
| coding.precision_ready | 0.966 | ≥ 0.98 | fail |
| coding.coverage_ready | 0.802 | ≥ 0.3 | pass |
| coding.document_accuracy | 0.950 | ≥ 0.9 | pass |
| checks.recall | 0.978 | ≥ 0.9 | pass |
| checks.precision | 1.000 | ≥ 0.9 | pass |
| checks.decoy_false_alarms | 0 | ≤ 0 | pass |
| close.deferral_recall | 0.907 | ≥ 0.9 | pass |
| close.accrual_recall | 1.000 | ≥ 0.9 | pass |
| close.precision | 0.966 | ≥ 0.95 | pass |
| close.cancelled_accrued | 0 | ≤ 0 | pass |

Model calls 0, cost $0.0000, p95 14 ms per document.
