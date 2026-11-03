# Release decision: production

On the `test` split (649 documents). **Do not ship.** Failed: close.accrual_recall.

| Gate | Value | Limit | Result |
|---|---|---|---|
| coding.precision_ready | 0.985 | ≥ 0.98 | pass |
| coding.coverage_ready | 0.612 | ≥ 0.3 | pass |
| coding.document_accuracy | 0.950 | ≥ 0.9 | pass |
| checks.recall | 0.976 | ≥ 0.9 | pass |
| checks.precision | 1.000 | ≥ 0.9 | pass |
| checks.decoy_false_alarms | 0 | ≤ 0 | pass |
| close.deferral_recall | 1.000 | ≥ 0.9 | pass |
| close.accrual_recall | 0.625 | ≥ 0.9 | fail |
| close.precision | 1.000 | ≥ 0.95 | pass |
| close.cancelled_accrued | 0 | ≤ 0 | pass |

Model calls 30, cost $0.0299, p95 18 ms per document.
