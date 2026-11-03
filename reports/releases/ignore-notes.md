# Release decision: ignore-notes

On the `test` split (663 documents). **Do not ship.** Failed: coding.precision_ready, coding.document_accuracy.

| Gate | Value | Limit | Result |
|---|---|---|---|
| coding.precision_ready | 0.917 | ≥ 0.98 | fail |
| coding.coverage_ready | 0.544 | ≥ 0.3 | pass |
| coding.document_accuracy | 0.839 | ≥ 0.9 | fail |
| checks.recall | 0.978 | ≥ 0.9 | pass |
| checks.precision | 1.000 | ≥ 0.9 | pass |
| checks.decoy_false_alarms | 0 | ≤ 0 | pass |
| close.deferral_recall | 0.944 | ≥ 0.9 | pass |
| close.accrual_recall | 1.000 | ≥ 0.9 | pass |
| close.precision | 1.000 | ≥ 0.95 | pass |
| close.cancelled_accrued | 0 | ≤ 0 | pass |

Model calls 0, cost $0.0000, p95 14 ms per document.
