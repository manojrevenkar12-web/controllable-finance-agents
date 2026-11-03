# Release decision: iban-from-history

On the `test` split (663 documents). **Do not ship.** Failed: checks.precision, checks.decoy_false_alarms.

| Gate | Value | Limit | Result |
|---|---|---|---|
| coding.precision_ready | 0.981 | ≥ 0.98 | pass |
| coding.coverage_ready | 0.629 | ≥ 0.3 | pass |
| coding.document_accuracy | 0.966 | ≥ 0.9 | pass |
| checks.recall | 0.956 | ≥ 0.9 | pass |
| checks.precision | 0.619 | ≥ 0.9 | fail |
| checks.decoy_false_alarms | 52 | ≤ 0 | fail |
| close.deferral_recall | 0.944 | ≥ 0.9 | pass |
| close.accrual_recall | 1.000 | ≥ 0.9 | pass |
| close.precision | 1.000 | ≥ 0.95 | pass |
| close.cancelled_accrued | 0 | ≤ 0 | pass |

Model calls 0, cost $0.0000, p95 16 ms per document.
