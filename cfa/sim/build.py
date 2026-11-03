"""Write the simulated world to data/: what the ledger holds, what arrives each evaluation month, and the truth."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .. import config
from .world import TenantWorld, build_world


def _booked(t: TenantWorld, months: set[str], noisy: bool = False) -> list[dict]:
    """Coded documents as the ledger holds them. History before the first evaluation month has the occasional
    miscoded line, as real ledgers do; later months were approved through the review and are clean."""
    world = config.load("world")
    accounts = sorted(a for a in world["accounts"] if a not in ("1900", "3070", "3300"))
    out = []
    for d in t.documents:
        if d.month in months:
            pub = d.public()
            pub["month"] = d.month
            coding = t.coding(d)
            if noisy:
                for i, c in enumerate(coding):
                    h = int(hashlib.sha256(f"{d.id}:{i}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
                    if h < world["noise"]["history_miscoded"]:
                        c["account"] = accounts[int(h * 1e6) % len(accounts)]
            pub["coding"] = coding
            out.append(pub)
    return out


def build() -> Path:
    world = config.load("world")
    tenants = build_world()
    history = set(world["months"]["history"])
    root = config.DATA
    (root / "world").mkdir(parents=True, exist_ok=True)
    seed = {
        "accounts": world["accounts"],
        "tax_keys": world["tax_keys"],
        "tenants": [
            {
                "id": t.id,
                "name": t.spec["name"],
                "cost_centres": t.spec["departments"],
                "materiality_eur": t.spec["materiality_eur"],
                "people": [asdict(p) for p in t.people],
                "suppliers": [
                    {k: v for k, v in asdict(s).items() if k not in ("categories", "new_in")}
                    for s in t.suppliers.values()
                ],
            }
            for t in tenants
        ],
        "documents": [d for t in tenants for d in _booked(t, history, noisy=True)],
    }
    (root / "world" / "seed.json").write_text(json.dumps(seed, ensure_ascii=False))
    earlier: set[str] = set()
    for split, month in world["months"]["splits"].items():
        folder = root / split
        folder.mkdir(parents=True, exist_ok=True)
        docs = [d.public() for t in tenants for d in t.documents if d.month == month]
        (folder / "documents.json").write_text(json.dumps({"month": month, "documents": docs}, ensure_ascii=False))
        (folder / "history.json").write_text(
            json.dumps([d for t in tenants for d in _booked(t, earlier)], ensure_ascii=False)
        )
        truth = {"month": month, "documents": {}, "close": {}, "decoys": []}
        for t in tenants:
            seen = {d.supplier_id for d in t.documents if d.month < month}
            for d in t.documents:
                if d.month == month:
                    truth["documents"][d.id] = {
                        "tenant": t.id,
                        "coding": t.coding(d),
                        "issues": t.issues.get(d.id, []),
                        "new_supplier": d.supplier_id not in seen,
                    }
            truth["close"][t.id] = t.close(month)
            truth["decoys"] += [x for x in t.decoys if x["document"] in truth["documents"]]
        (folder / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1))
        earlier.add(month)
    # bank-detail changes verified after the seed was taken are part of each month's supplier master
    (root / "world" / "suppliers_final.json").write_text(
        json.dumps(
            {t.id: [asdict(s) | {"categories": None} for s in t.suppliers.values()] for t in tenants},
            ensure_ascii=False,
        )
    )
    return root
