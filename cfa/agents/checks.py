"""Pre-payment checks: what must be looked at before an invoice is paid.

Rules decide; nothing here is a model's guess. Each finding names its evidence so the accountant can confirm it
(payment goes on hold) or dismiss it. Five checks:

- duplicate: the same supplier's invoice number again (ignoring punctuation, case and leading zeros), or the
  same amount and lines within a few days
- bank details: an IBAN that is not the supplier's verified one (the classic payment-diversion fraud). Compared
  with the supplier master, which includes verified changes; comparing with past invoices instead flags every
  legitimate, verified change
- VAT rate: a line at a rate this company has never seen for that item
- reverse charge: German VAT charged by a supplier from another EU country for a service
- arithmetic: lines, VAT and totals that do not add up
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .. import config
from .coding import item_key


@dataclass
class Finding:
    issue: str
    document: str
    detail: str
    evidence: list[dict]
    line: int | None = None


def eur(cents: int) -> str:
    s = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if cents < 0 else ''}{s} €"


def normalise_number(number: str) -> str:
    parts = re.findall(r"[a-z]+|\d+", number.lower())
    return "".join(p.lstrip("0") or "0" if p.isdigit() else p for p in parts)


def valid_iban(supplier: dict, date: str) -> str | None:
    """The account on file on a given day: changes count from the day they were verified."""
    changes = sorted(supplier.get("bank_changes") or [], key=lambda c: c["verified_at"])
    later = [c for c in changes if c["verified_at"] > date]
    return later[0]["old_iban"] if later else supplier.get("iban")


class Checker:
    def __init__(self, history_docs: list[dict], bookings: list[dict], suppliers: dict[str, dict]):
        self.cfg = config.load("agents")["checks"]
        self.suppliers = suppliers
        self.by_supplier: dict[str, list[dict]] = defaultdict(list)
        for d in history_docs:
            self.by_supplier[d["supplier_id"]].append(d)
        self.rates: dict[str, Counter] = defaultdict(Counter)
        self.paid_ibans: dict[str, set[str]] = defaultdict(set)
        self.supplier_rates: dict[str, Counter] = defaultdict(Counter)
        for b in bookings:
            if b.get("supplier_country", "DE") != "DE":
                continue  # reverse-charge invoices show no VAT; they say nothing about the item's rate
            line = b["line"] or {}
            rate = round(float(line.get("vat_rate", 0)), 2)
            self.rates[item_key(line.get("description", ""))][rate] += 1
            self.supplier_rates[b["supplier_id"]][rate] += 1
        for d in history_docs:
            if d.get("iban"):
                self.paid_ibans[d["supplier_id"]].add(d["iban"])

    def check(self, doc: dict, same_month: list[dict]) -> list[Finding]:
        out: list[Finding] = []
        out += self._duplicate(doc, same_month)
        if doc["kind"] == "invoice":
            out += self._bank(doc)
            out += self._reverse_charge(doc)
        out += self._vat(doc)
        out += self._arithmetic(doc)
        return out

    def _duplicate(self, doc: dict, same_month: list[dict]) -> list[Finding]:
        window = dt.timedelta(days=self.cfg["duplicate_window_days"])
        mine = normalise_number(doc["number"])
        date = dt.date.fromisoformat(doc["date"])
        earlier = [
            d
            for d in self.by_supplier[doc["supplier_id"]] + same_month
            if d["supplier_id"] == doc["supplier_id"]
            and d["id"] != doc["id"]
            and (d["date"], d["id"]) < (doc["date"], doc["id"])
        ]
        for d in earlier:
            same_number = normalise_number(d["number"]) == mine
            same_content = (
                d["gross_total"] == doc["gross_total"]
                and abs(dt.date.fromisoformat(d["date"]) - date) <= window
                and [x["description"] for x in d["lines"]] == [x["description"] for x in doc["lines"]]
            )
            if same_number or same_content:
                why = "the same invoice number" if same_number else "the same amount and lines a few days apart"
                return [
                    Finding(
                        "duplicate",
                        doc["id"],
                        f"{why} as {d['id']} ({d['number']}, {d['date']})",
                        [{"document": d["id"], "number": d["number"], "date": d["date"], "gross": d["gross_total"]}],
                    )
                ]
        return []

    def _bank(self, doc: dict) -> list[Finding]:
        iban = (doc.get("iban") or "").replace(" ", "")
        s = self.suppliers.get(doc["supplier_id"]) or {}
        if not iban:
            return []
        if self.cfg["bank_details"] == "history":
            known = self.paid_ibans[doc["supplier_id"]]
            if known and iban not in known:
                return [
                    Finding(
                        "iban_changed",
                        doc["id"],
                        "bank details differ from earlier invoices",
                        [{"invoice_iban": iban, "earlier": sorted(known)}],
                    )
                ]
            return []
        valid = valid_iban(s, doc["date"])
        if valid and iban != valid:
            return [
                Finding(
                    "iban_changed",
                    doc["id"],
                    "bank details differ from the supplier's account verified for the invoice date",
                    [{"invoice_iban": iban, "verified_iban": valid, "verified_changes": s.get("bank_changes", [])}],
                )
            ]
        return []

    def _reverse_charge(self, doc: dict) -> list[Finding]:
        if doc["supplier_country"] in self.cfg["eu_countries"] and doc["vat_total"] > 0:
            return [
                Finding(
                    "reverse_charge_missing",
                    doc["id"],
                    f"a supplier from {doc['supplier_country']} charged German VAT; services from other EU countries "
                    "fall under reverse charge (§ 13b UStG)",
                    [{"country": doc["supplier_country"], "vat": doc["vat_total"]}],
                )
            ]
        return []

    def _vat(self, doc: dict) -> list[Finding]:
        out = []
        for i, x in enumerate(doc["lines"]):
            rate = round(float(x["vat_rate"]), 2)
            if doc["supplier_country"] != "DE" and rate in (0.0, 0.19):
                continue
            seen = self.rates.get(item_key(x["description"]))
            basis = "lines of this item"
            if not seen or sum(seen.values()) < self.cfg["vat_min_history"]:
                # an item never bought before: a supplier that only ever charged one rate is the next best evidence
                seen = self.supplier_rates.get(doc["supplier_id"])
                basis = "lines from this supplier"
                if not seen or len(seen) != 1 or sum(seen.values()) < self.cfg["vat_min_history"]:
                    continue
            if rate in seen:
                continue
            usual = seen.most_common(1)[0][0]
            out.append(
                Finding(
                    "vat_rate_wrong",
                    doc["id"],
                    f"line {i + 1} '{x['description']}' at {rate:.0%}; this company's "
                    f"{sum(seen.values())} earlier {basis} were at {usual:.0%}",
                    [{"line": i, "rate": rate, "usual": usual, "seen": {str(k): v for k, v in seen.items()}}],
                    line=i,
                )
            )
        return out

    def _arithmetic(self, doc: dict) -> list[Finding]:
        tol = self.cfg["rounding_tolerance_cents"]
        problems = []
        for i, x in enumerate(doc["lines"]):
            if abs(round(x["net"] * float(x["vat_rate"])) - x["vat"]) > tol:
                problems.append(f"line {i + 1}: VAT {eur(x['vat'])} is not {x['vat_rate']:.0%} of {eur(x['net'])}")
        if sum(x["net"] for x in doc["lines"]) != doc["net_total"]:
            problems.append("lines do not add up to the net total")
        if abs(sum(x["vat"] for x in doc["lines"]) - doc["vat_total"]) > tol:
            problems.append("line VAT does not add up to the VAT total")
        if doc["net_total"] + doc["vat_total"] != doc["gross_total"]:
            problems.append(
                f"net {eur(doc['net_total'])} + VAT {eur(doc['vat_total'])} = "
                f"{eur(doc['net_total'] + doc['vat_total'])}, but the invoice says {eur(doc['gross_total'])}"
            )
        if problems:
            return [Finding("arithmetic", doc["id"], "; ".join(problems), [{"problems": problems}])]
        return []
