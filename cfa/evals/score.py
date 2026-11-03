"""Score what the agents proposed against the truth of the month.

Coding is scored per document (all lines right) and per line, by bucket: *ready* (confident, approved in bulk),
*review* (a suggestion a person checks) and *person* (no suggestion). The number that matters most is the
precision of *ready*: a wrong booking that nobody looks at is the expensive mistake. Checks are scored per issue
type, with false alarms on decoys (verified bank changes, recurring invoices with the same amount) counted
separately. Close entries must match to the cent.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import numpy as np

ISSUES = ("duplicate", "iban_changed", "vat_rate_wrong", "reverse_charge_missing", "arithmetic")


def ratio(k: float, n: float) -> float | None:
    return None if n == 0 else k / n


def bootstrap(rows: list[tuple[float, float]], b: int = 2000, seed: int = 7) -> tuple[float | None, float | None]:
    """Interval for sum(k)/sum(n) over resampled rows (documents)."""
    if not rows:
        return None, None
    arr = np.array(rows, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(b, len(arr)))
    k, n = arr[:, 0][idx].sum(axis=1), arr[:, 1][idx].sum(axis=1)
    vals = np.where(n > 0, k / np.where(n > 0, n, 1), np.nan)
    vals = vals[~np.isnan(vals)]
    return (float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))) if len(vals) else (None, None)


def metric(rows: list[tuple[float, float]]) -> dict:
    k, n = sum(r[0] for r in rows), sum(r[1] for r in rows)
    lo, hi = bootstrap(rows)
    return {"value": ratio(k, n), "low": lo, "high": hi, "k": k, "n": n}


def score(truth: dict, proposals: dict[str, list[dict]], documents: dict[str, dict]) -> dict:
    """proposals: tenant -> list of proposals as the ledger returns them."""
    by_doc: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    journal: dict[str, list[dict]] = defaultdict(list)
    for tenant, props in proposals.items():
        for p in props:
            if p["kind"] == "journal":
                journal[tenant].append(p)
            else:
                by_doc[p["document_id"]][p["kind"]].append(p)

    # ---------------------------------------------------------------------------------------- coding
    rows: dict[str, list[tuple[float, float]]] = defaultdict(list)
    buckets: Counter[str] = Counter()
    for doc_id, t in truth["documents"].items():
        coding = by_doc[doc_id]["coding"]
        if not coding:
            buckets["person"] += 1
            rows["coverage_ready"].append((0, 1))
            rows["auto_or_suggested"].append((0, 1))
            if t["new_supplier"]:
                rows["new_supplier_suggested"].append((0, 1))
            continue
        p = coding[0]
        bucket = (p["evidence"] or [{}])[0].get("bucket", "review")
        sources = (p["evidence"] or [{}])[0].get("sources", [])
        buckets[bucket] += 1
        lines = p["payload"]["lines"]
        right_lines = [
            x["account"] == y["account"] and x["cost_centre"] == y["cost_centre"] and x["tax_key"] == y["tax_key"]
            for x, y in zip(lines, t["coding"], strict=True)
        ]
        doc_right = all(right_lines)
        rows["coverage_ready"].append((bucket == "ready", 1))
        rows["auto_or_suggested"].append((1, 1))
        rows[f"precision_{bucket}"].append((doc_right, 1))
        rows["document_accuracy"].append((doc_right, 1))
        for ok, x, y, src in zip(right_lines, lines, t["coding"], sources or ["pattern"] * len(lines), strict=False):
            rows["line_accuracy"].append((ok, 1))
            rows["account_accuracy"].append((x["account"] == y["account"], 1))
            rows["cost_centre_accuracy"].append((x["cost_centre"] == y["cost_centre"], 1))
            rows["tax_key_accuracy"].append((x["tax_key"] == y["tax_key"], 1))
            rows[f"line_accuracy_{src}"].append((ok, 1))
        if t["new_supplier"]:
            rows["new_supplier_suggested"].append((1, 1))
            rows["new_supplier_accuracy"].append((doc_right, 1))
    coding_out = {k: metric(v) for k, v in sorted(rows.items())}
    coding_out["buckets"] = dict(buckets)

    # ---------------------------------------------------------------------------------------- checks
    decoys = {
        (d["document"], {"iban_changed_verified": "iban_changed", "same_amount_new_number": "duplicate"}[d["type"]])
        for d in truth["decoys"]
    }
    per = {i: {"tp": 0, "fp": 0, "fn": 0} for i in ISSUES}
    decoy_alarms: Counter[str] = Counter()
    for doc_id, t in truth["documents"].items():
        want = {i["type"] for i in t["issues"]}
        got = {p["payload"]["issue"] for p in by_doc[doc_id]["check"]}
        for i in ISSUES:
            if i in want and i in got:
                per[i]["tp"] += 1
            elif i in got:
                per[i]["fp"] += 1
                if (doc_id, i) in decoys:
                    decoy_alarms[i] += 1
            elif i in want:
                per[i]["fn"] += 1
    checks_out = {
        i: {**v, "precision": ratio(v["tp"], v["tp"] + v["fp"]), "recall": ratio(v["tp"], v["tp"] + v["fn"])}
        for i, v in per.items()
    }
    tp = sum(v["tp"] for v in per.values())
    fp = sum(v["fp"] for v in per.values())
    fn = sum(v["fn"] for v in per.values())
    checks_out["all"] = {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "decoys": len(decoys),
        "decoy_false_alarms": sum(decoy_alarms.values()),
    }

    # ----------------------------------------------------------------------------------------- close
    close: dict[str, Any] = {
        "deferral": {"tp": 0, "fp": 0, "fn": 0},
        "accrual": {"tp": 0, "fp": 0, "fn": 0},
        "cancelled_accrued": 0,
        "near_misses": [],
    }
    for tenant, c in truth["close"].items():
        want_d = {(e["document"], e["credit"], e["amount"]) for e in c["deferrals"]}
        want_a = {(e["supplier"], e["debit"], e["amount"], e["cost_centre"]) for e in c["accruals"]}
        cancelled = {x["supplier"] for x in c["decoys"]}
        got_d, got_a = set(), set()
        for p in journal[tenant]:
            j = p["payload"]
            if j["type"] == "deferral":
                got_d.add((p["document_id"], j["credit"], j["amount_cents"]))
            elif j["type"] == "accrual":
                got_a.add((j["supplier_id"], j["debit"], j["amount_cents"], j["cost_centre"]))
                close["cancelled_accrued"] += j["supplier_id"] in cancelled
        for kind, want, got in (("deferral", want_d, got_d), ("accrual", want_a, got_a)):
            close[kind]["tp"] += len(want & got)
            close[kind]["fp"] += len(got - want)
            close[kind]["fn"] += len(want - got)
            for g in sorted(got - want):
                close["near_misses"].append(
                    {
                        "kind": kind,
                        "tenant": tenant,
                        "proposed": list(g),
                        "expected": [list(w) for w in want if w[0] == g[0]],
                    }
                )
    for kind in ("deferral", "accrual"):
        v = close[kind]
        v["precision"], v["recall"] = ratio(v["tp"], v["tp"] + v["fp"]), ratio(v["tp"], v["tp"] + v["fn"])
    return {"documents": len(truth["documents"]), "coding": coding_out, "checks": checks_out, "close": close}
