"""Load a split's world into the ledger: companies, people, suppliers as of that month, coded history, and the
month's documents as received. Runs as the database owner (a seeding job, not the service)."""

from __future__ import annotations

import json
import os

import psycopg
from psycopg.types.json import Jsonb

from .. import config
from ..sim.world import month_bounds
from .migrate import down, ensure_runtime_role, up


def owner_url() -> str:
    db = config.load("ledger")["database"]
    return os.environ.get(db["owner_url_env"], db["default_owner_url"])


def supplier_master(final: dict, month: str) -> tuple[str, list[dict]]:
    """Bank details as they stood in a month: only changes verified by its last day count."""
    end = month_bounds(month)[1].isoformat()
    changes = sorted(final["iban_changes"], key=lambda c: c["verified_at"])
    if not changes:
        return final["iban"], []
    known = [c for c in changes if c["verified_at"] <= end]
    return (known[-1]["new"] if known else changes[0]["old"]), known


def seed(split: str, url: str | None = None, reset: bool = True) -> dict:
    url = url or owner_url()
    month = config.load("world")["months"]["splits"][split]
    world = json.loads((config.DATA / "world" / "seed.json").read_text())
    final = json.loads((config.DATA / "world" / "suppliers_final.json").read_text())
    history = world["documents"] + json.loads((config.DATA / split / "history.json").read_text())
    incoming = json.loads((config.DATA / split / "documents.json").read_text())["documents"]
    if reset:
        down(url)
    up(url)
    ensure_runtime_role(url, os.environ.get("CFA_APP_PASSWORD", "cfa_app"))
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        for t in world["tenants"]:
            cur.execute(
                "insert into tenants (id, name, materiality_cents) values (%s, %s, %s)",
                (t["id"], t["name"], int(t["materiality_eur"] * 100)),
            )
            cur.executemany(
                "insert into people (id, tenant_id, name, email, department, role) values (%s, %s, %s, %s, %s, %s)",
                [(x["id"], t["id"], x["name"], x["email"], x["department"], x["role"]) for x in t["people"]],
            )
            cur.executemany(
                "insert into cost_centres (tenant_id, department, code) values (%s, %s, %s)",
                [(t["id"], d, c) for d, c in t["cost_centres"].items()],
            )
            cur.executemany(
                "insert into accounts (tenant_id, number, name) values (%s, %s, %s)",
                [(t["id"], n, name) for n, name in world["accounts"].items()],
            )
            for s in final[t["id"]]:
                iban, changes = supplier_master(s, month)
                cur.execute(
                    "insert into suppliers (id, tenant_id, name, country, vat_id, iban) values (%s, %s, %s, %s, %s, %s)",
                    (s["id"], t["id"], s["name"], s["country"], s["vat_id"], iban),
                )
                cur.executemany(
                    "insert into supplier_bank_changes (tenant_id, supplier_id, old_iban, new_iban, verified_at, verified_by) "
                    "values (%s, %s, %s, %s, %s, 'supplier desk')",
                    [(t["id"], s["id"], c["old"], c["new"], c["verified_at"]) for c in changes],
                )

        def insert(d: dict, status: str) -> None:
            cur.execute(
                "insert into documents (id, tenant_id, kind, supplier_id, number, doc_date, due_date, iban, requester_id, "
                "net_total, vat_total, gross_total, notes, lines, month, status) values "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    d["id"],
                    d["tenant"],
                    d["kind"],
                    d["supplier_id"],
                    d["number"],
                    d["date"],
                    d["due_date"],
                    d["iban"],
                    d["requester"],
                    d["net_total"],
                    d["vat_total"],
                    d["gross_total"],
                    d["notes"],
                    Jsonb(d["lines"]),
                    d.get("month") or month,
                    status,
                ),
            )

        for d in history:
            insert(d, "booked")
            cur.executemany(
                "insert into bookings (document_id, line_no, tenant_id, account, cost_centre, tax_key, booked_by) "
                "values (%s, %s, %s, %s, %s, %s, 'history')",
                [
                    (d["id"], i, d["tenant"], c["account"], c["cost_centre"], c["tax_key"])
                    for i, c in enumerate(d["coding"])
                ],
            )
        for d in incoming:
            insert(d, "received")
            cur.execute(
                "insert into outbox (tenant_id, topic, key, payload) values (%s, 'document.received', %s, %s)",
                (d["tenant"], d["id"], Jsonb({"event": "document.received", "document": d["id"], "month": month})),
            )
        conn.commit()
    return {"split": split, "month": month, "history": len(history), "incoming": len(incoming)}
