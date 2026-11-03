"""Run a held-out case set against the close agent and the checks, once, and keep what happened.

The first run of a set goes to reports/heldout/<set>/first_run.json and is never rewritten; later runs go to
latest_run.json. The close runs with the model enabled (answers cached in fixtures/llm_cache), as in production.
"""

from __future__ import annotations

import datetime as dt
import json

import yaml

from .. import config
from ..agents.checks import Checker
from ..agents.close import close_month


def _entry_key(e: dict) -> tuple:
    if e["type"] == "deferral":
        return (
            "deferral",
            e.get("document_id"),
            str(e["debit"]),
            str(e["credit"]),
            int(e["amount_cents"]),
            str(e["cost_centre"]),
        )
    return (
        "accrual",
        e.get("supplier_id"),
        str(e["debit"]),
        str(e["credit"]),
        int(e["amount_cents"]),
        str(e["cost_centre"]),
    )


def run_close(case: dict) -> tuple[set, set, list[str]]:
    docs = []
    for d in case["documents"]:
        docs.append({**d, "supplier_name": d.get("supplier_name", d["supplier_id"]), "notes": d.get("notes", "")})
    codings = {d["id"]: d["coding"] for d in case["documents"]}
    history = [
        {**h, "notes": h.get("notes", ""), "supplier_name": h.get("supplier_name", h["supplier_id"])}
        for h in case.get("history", [])
    ]
    res = close_month(
        case["month"], docs, codings, history, int(case["materiality_cents"]), set(case.get("duplicates") or [])
    )
    got = set()
    for e in res.entries:
        got.add(
            _entry_key(
                {
                    "type": e.type,
                    "document_id": e.document_id,
                    "supplier_id": e.supplier_id,
                    "debit": e.debit,
                    "credit": e.credit,
                    "amount_cents": e.amount_cents,
                    "cost_centre": e.cost_centre,
                }
            )
        )
    want = {_entry_key(e) for e in case["expect"]["entries"]}
    return want, got, [e.reasoning for e in res.entries]


def run_check(case: dict) -> tuple[set, set, list[str]]:
    bookings = [
        {
            "supplier_id": b["supplier_id"],
            "supplier_country": b.get("supplier_country", "DE"),
            "line": {"description": b["description"], "vat_rate": b["vat_rate"]},
        }
        for b in case.get("booked_lines", [])
    ]
    suppliers = {
        k: {"iban": v.get("iban"), "bank_changes": v.get("bank_changes", [])}
        for k, v in (case.get("suppliers") or {}).items()
    }
    checker = Checker(case.get("history", []), bookings, suppliers)
    found = checker.check(case["document"], case.get("same_month", []))
    return set(case["expect"]["issues"]), {f.issue for f in found}, [f.detail for f in found]


def run(name: str) -> dict:
    folder = config.ROOT / "heldout" / name
    cases = yaml.safe_load((folder / "cases.yaml").read_text())
    status = (folder / "STATUS").read_text().strip()
    results = []
    for c in cases:
        try:
            want, got, why = run_close(c) if c["kind"] == "close" else run_check(c)
            ok = want == got
            results.append(
                {
                    "id": c["id"],
                    "kind": c["kind"],
                    "pass": ok,
                    "expected": sorted(map(str, want)),
                    "got": sorted(map(str, got)),
                    "agent_said": why,
                    "case_why": c.get("why", ""),
                }
            )
        except Exception as e:  # a case the agent cannot even process is a failure, recorded as such
            results.append({"id": c["id"], "kind": c["kind"], "pass": False, "error": f"{type(e).__name__}: {e}"})
    report = {
        "set": name,
        "status": status,
        "ran_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "cases": len(results),
        "passed": sum(r["pass"] for r in results),
        "by_kind": {
            k: {
                "cases": sum(r["kind"] == k for r in results),
                "passed": sum(r["pass"] for r in results if r["kind"] == k),
            }
            for k in ("close", "check")
        },
        "failures": [r for r in results if not r["pass"]],
    }
    out = config.REPORTS / "heldout" / name
    out.mkdir(parents=True, exist_ok=True)
    first = out / "first_run.json"
    target = out / "latest_run.json" if first.exists() else first
    target.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    report["recorded_as"] = target.name
    return report
