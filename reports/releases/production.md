# Release decision: production

On the `test` split (663 documents). **Ship.**

| Gate | Value | Limit | Result |
|---|---|---|---|
| coding.precision_ready | 0.981 | ≥ 0.98 | pass |
| coding.coverage_ready | 0.629 | ≥ 0.3 | pass |
| coding.document_accuracy | 0.950 | ≥ 0.9 | pass |
| checks.recall | 0.978 | ≥ 0.9 | pass |
| checks.precision | 1.000 | ≥ 0.9 | pass |
| checks.decoy_false_alarms | 0 | ≤ 0 | pass |
| close.deferral_recall | 1.000 | ≥ 0.9 | pass |
| close.accrual_recall | 1.000 | ≥ 0.9 | pass |
| close.precision | 1.000 | ≥ 0.95 | pass |
| close.cancelled_accrued | 0 | ≤ 0 | pass |

Model calls 34, cost $0.0351, p95 17 ms per document.
