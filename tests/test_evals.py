"""Scoring and gates, on hand-made proposals."""

from cfa import config
from cfa.evals.calibrate import choose
from cfa.evals.gate import decide
from cfa.evals.run import variant
from cfa.evals.score import score

TRUTH = {
    "documents": {
        "d1": {
            "tenant": "t",
            "coding": [{"account": "6815", "cost_centre": "1", "tax_key": "VSt19"}],
            "issues": [],
            "new_supplier": False,
        },
        "d2": {
            "tenant": "t",
            "coding": [{"account": "6837", "cost_centre": "2", "tax_key": "VSt19"}],
            "issues": [{"type": "duplicate"}],
            "new_supplier": True,
        },
        "d3": {
            "tenant": "t",
            "coding": [{"account": "6400", "cost_centre": "1", "tax_key": "NONE"}],
            "issues": [],
            "new_supplier": False,
        },
    },
    "decoys": [{"type": "iban_changed_verified", "document": "d3"}],
    "close": {
        "t": {
            "deferrals": [{"document": "d1", "credit": "6815", "amount": 1000}],
            "accruals": [{"supplier": "s", "debit": "6805", "amount": 500, "cost_centre": "1"}],
            "decoys": [{"type": "cancelled_contract", "supplier": "gone"}],
        }
    },
}


def coding(doc, account, cc, tax, bucket):
    return {
        "kind": "coding",
        "document_id": doc,
        "payload": {"lines": [{"line_no": 0, "account": account, "cost_centre": cc, "tax_key": tax}]},
        "evidence": [{"bucket": bucket, "sources": ["pattern"]}],
    }


def journal(type_, **kw):
    return {"kind": "journal", "document_id": kw.pop("document_id", None), "payload": {"type": type_, **kw}}


PROPOSALS = {
    "t": [
        coding("d1", "6815", "1", "VSt19", "ready"),
        coding("d2", "6815", "2", "VSt19", "review"),
        {"kind": "check", "document_id": "d2", "payload": {"issue": "duplicate"}},
        {"kind": "check", "document_id": "d3", "payload": {"issue": "iban_changed"}},
        journal("deferral", document_id="d1", credit="6815", amount_cents=1000),
        journal("accrual", supplier_id="s", debit="6805", amount_cents=501, cost_centre="1"),
        journal("accrual", supplier_id="gone", debit="6805", amount_cents=10, cost_centre="1"),
    ]
}


def test_score_buckets_checks_and_close():
    r = score(TRUTH, PROPOSALS, {})
    c = r["coding"]
    assert c["buckets"] == {"ready": 1, "review": 1, "person": 1}
    assert c["precision_ready"]["value"] == 1.0 and c["precision_review"]["value"] == 0.0
    assert c["coverage_ready"]["value"] == 1 / 3
    assert r["checks"]["duplicate"]["tp"] == 1 and r["checks"]["all"]["decoy_false_alarms"] == 1
    assert r["close"]["deferral"]["tp"] == 1
    assert r["close"]["accrual"] == {
        "tp": 0,
        "fp": 2,
        "fn": 1,
        "precision": 0.0,
        "recall": 0.0,
    }  # one cent off is wrong
    assert r["close"]["cancelled_accrued"] == 1


def test_gate_fails_on_any_floor():
    r = score(TRUTH, PROPOSALS, {})
    r.update({"agent": "x", "split": "test"})
    d = decide(r)
    assert not d["ship"] and "checks.decoy_false_alarms" in d["failed"] and "close.cancelled_accrued" in d["failed"]


def test_threshold_is_the_lowest_that_meets_the_target():
    data = [(0.9, True)] * 50 + [(0.6, True)] * 40 + [(0.6, False)] * 2 + [(0.3, False)] * 10
    best = choose(data, 0.97, 30)
    assert best["ready_confidence"] == 0.6 and best["documents"] == 92
    assert choose(data, 1.0, 30)["ready_confidence"] == 0.9
    assert choose([(0.5, False)] * 40, 0.99, 30)["ready_confidence"] > 1


def test_variants_override_only_what_they_name():
    base = config.load("agents")
    with variant("iban-from-history") as v:
        assert v["checks"]["bank_details"] == "history" and v["coding"] == base["coding"]
        assert config.load("agents")["checks"]["bank_details"] == "history"
    assert config.load("agents")["checks"]["bank_details"] == "master"
