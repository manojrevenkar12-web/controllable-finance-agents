"""Generate the simulated companies, their history and the evaluation months, with the truth kept apart.

Everything is reproducible from the seed in ``config/sim.yaml``-free form: one random stream per company,
derived from the company id, so adding a company does not change the others. Money is integer cents.

Outputs (``cfa.sim.build``):
    data/world/seed.json            companies, people, chart, cost centres, suppliers (with verified bank
                                    changes) and every document before the first evaluation month, coded
    data/<split>/documents.json     what arrives in the evaluation month (what agents see)
    data/<split>/truth.json         per document: the coding of each line and its issues; per company: the
                                    month-end deferrals and accruals; the decoys
    data/<split>/history.json       the coded documents of earlier evaluation months (booked before this one)
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import random
from dataclasses import asdict, dataclass, field

from .. import config

FIRST_NAMES = [
    "Anna",
    "Jonas",
    "Lea",
    "Felix",
    "Mia",
    "Paul",
    "Emma",
    "Ben",
    "Clara",
    "Noah",
    "Ida",
    "Elias",
    "Lina",
    "Finn",
    "Mila",
    "Theo",
    "Ella",
    "Henri",
    "Nora",
    "Luca",
]
LAST_NAMES = [
    "Becker",
    "Schulz",
    "Wagner",
    "Hoffmann",
    "Koch",
    "Richter",
    "Klein",
    "Wolf",
    "Neumann",
    "Schwarz",
    "Krüger",
    "Hartmann",
    "Lange",
    "Werner",
    "Krause",
    "Lehmann",
    "Köhler",
    "Maier",
    "Frank",
    "Berger",
]


def cents_round(x: float) -> int:
    """Half away from zero, as commercial rounding does."""
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def month_bounds(month: str) -> tuple[dt.date, dt.date]:
    y, m = map(int, month.split("-"))
    return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])


def add_months(month: str, n: int) -> str:
    y, m = map(int, month.split("-"))
    k = y * 12 + (m - 1) + n
    return f"{k // 12:04d}-{k % 12 + 1:02d}"


def fmt_eur(cents: int) -> str:
    s = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{s}" if cents < 0 else s


@dataclass
class Person:
    id: str
    name: str
    email: str
    department: str
    role: str  # employee | approver | accountant | admin


@dataclass
class Supplier:
    id: str
    name: str
    country: str
    vat_id: str
    iban: str  # the verified bank account on file
    categories: list[str]
    iban_changes: list[dict] = field(default_factory=list)  # {old, new, verified_at}
    new_in: str | None = None


@dataclass
class Line:
    description: str
    net: int
    vat_rate: float
    vat: int
    category: str  # truth only; not exported to documents


@dataclass
class Document:
    id: str
    tenant: str
    kind: str  # invoice | card
    supplier_id: str
    supplier_name: str
    supplier_country: str
    supplier_vat_id: str
    number: str
    date: str
    due_date: str
    iban: str | None
    requester: str
    lines: list[Line]
    net_total: int
    vat_total: int
    gross_total: int
    notes: str
    month: str
    service_start: str | None = None  # truth only
    service_end: str | None = None  # truth only
    recurring_key: str | None = None  # truth only
    cc_department: str | None = None  # truth only: a note assigns the document to this department

    def public(self) -> dict:
        d = asdict(self)
        for k in ("service_start", "service_end", "recurring_key", "month", "cc_department"):
            d.pop(k)
        d["lines"] = [{k: v for k, v in asdict(line).items() if k != "category"} for line in self.lines]
        d["currency"] = "EUR"
        return d


class TenantWorld:
    def __init__(self, spec: dict, world: dict):
        self.spec = spec
        self.world = world
        self.id = spec["id"]
        self.rng = random.Random(int(hashlib.sha256(self.id.encode()).hexdigest()[:12], 16))
        self.people: list[Person] = []
        self.suppliers: dict[str, Supplier] = {}
        self.documents: list[Document] = []
        self.recurring: dict[str, dict] = {}  # key -> {supplier, category, base_net, active_until}
        self.issues: dict[str, list[dict]] = {}
        self.decoys: list[dict] = []
        self.missing: dict[str, list[str]] = {}  # month -> recurring keys withheld
        self.cancelled: dict[str, list[str]] = {}  # month -> keys whose last invoice came the month before
        self.seq = 0
        self.numbers: dict[str, int] = {}
        sku_rng = random.Random(7)  # catalogues are the same for every company
        self.skus = {
            c: [f"{sku_rng.randrange(10000, 99999)}" for _ in range(world["noise"]["skus_per_category"])]
            for c in world["categories"]
        }
        self.first_eval = min(world["months"]["splits"].values())
        self._people()
        self._suppliers()

    # ------------------------------------------------------------------------------------------ set-up

    def _people(self) -> None:
        rng = self.rng
        depts = list(self.spec["departments"])
        names = rng.sample([(f, n) for f in FIRST_NAMES for n in LAST_NAMES], 16)
        domain = self.id.removeprefix("t-") + ".example"
        for i, (f, n) in enumerate(names):
            dept = depts[i % len(depts)]
            role = (
                "approver"
                if i < len(depts)
                else "accountant"
                if i < len(depts) + 2
                else "admin"
                if i == len(depts) + 2
                else "employee"
            )
            if role in ("accountant", "admin"):
                dept = "ADMIN"
            self.people.append(
                Person(
                    f"{self.id}-u{i:02d}",
                    f"{f} {n}",
                    f"{f.lower()}.{n.lower()}@{domain}".replace("ü", "ue").replace("ö", "oe"),
                    dept,
                    role,
                )
            )

    def _iban(self) -> str:
        bank = self.rng.choice(["10070000", "10010010", "20040000", "37040044", "50010517", "70020270"])
        acct = f"{self.rng.randrange(10**9, 10**10)}"
        bban = bank + acct
        # ISO 13616 check digits for DE
        num = int("".join(str(int(c, 36)) for c in bban + "DE00"))
        check = 98 - num % 97
        return f"DE{check:02d}{bban}"

    def _suppliers(self) -> None:
        for i, s in enumerate(self.world["suppliers"]):
            if (
                self.rng.random() < 0.8
                or s.get("new_in")
                or any(c in self.world["recurring_categories"] for c in s["categories"])
            ):
                country = s["country"]
                vat_id = f"{country}{self.rng.randrange(10**8, 10**9)}"
                self.suppliers[f"s{i:02d}"] = Supplier(
                    f"{self.id}-s{i:02d}",
                    s["name"],
                    country,
                    vat_id,
                    self._iban(),
                    list(s["categories"]),
                    new_in=s.get("new_in"),
                )
        # one recurring relationship per recurring category, picked among long-standing suppliers
        for cat in self.world["recurring_categories"]:
            options = [k for k, s in self.suppliers.items() if cat in s.categories and not s.new_in]
            k = self.rng.choice(options)
            base = {"rent": (450_000, 1_400_000), "cloud": (60_000, 480_000), "telecom": (12_000, 90_000)}[cat]
            self.recurring[f"{cat}:{k}"] = {
                "supplier": k,
                "category": cat,
                "base": self.rng.randrange(*base),
                "until": None,
            }

    # --------------------------------------------------------------------------------------- documents

    def _next_id(self, kind: str) -> str:
        self.seq += 1
        return f"{self.id}-{'inv' if kind == 'invoice' else 'card'}-{self.seq:05d}"

    def _date_in(self, month: str, lo: int = 1, hi: int = 28) -> dt.date:
        start, end = month_bounds(month)
        return start + dt.timedelta(days=self.rng.randrange(lo - 1, min(hi, end.day)))

    def _requester(self, category: str) -> Person:
        if category in ("rent", "insurance", "legal"):
            return self.rng.choice([p for p in self.people if p.role in ("accountant", "admin")])
        return self.rng.choice(self.people)

    def _line(
        self, category: str, net: int, words: list[str] | None = None, month: str = "", mixed: bool = False
    ) -> Line:
        cat = self.world["categories"][category]
        pool = words or cat["words"]
        if not words and month >= self.first_eval and cat.get("new_words") and self.rng.random() < 0.25:
            pool = cat["new_words"]
        if mixed and self.rng.random() < self.world["noise"]["sku_share"]:
            rate = float(cat["vat"])
            sku = self.rng.choice(self.skus[category])
            return Line(f"Art.-Nr. {sku}", net, rate, cents_round(net * rate), category)
        word = self.rng.choice(pool)
        extra = self.rng.choice(
            ["", "", f" ({self.rng.randrange(1, 12)} Stk.)", " – Pauschale", f" Pos. {self.rng.randrange(10, 99)}"]
        )
        rate = float(cat["vat"])
        return Line(f"{word}{extra}", net, rate, cents_round(net * rate), category)

    def _invoice_number(self, s: Supplier, date: dt.date) -> str:
        style = int(hashlib.sha256(s.name.encode()).hexdigest(), 16) % 4
        # suppliers number invoices in sequence (with gaps: they invoice other customers too)
        last = self.numbers.get(s.id, self.rng.randrange(100, 3000))
        n = self.numbers[s.id] = last + self.rng.randrange(1, 40)
        return [f"RE-{date.year}-{n:04d}", f"INV{date.year}{n:05d}", f"{date:%y%m}-{n}", f"R{n:06d}"][style]

    def _make(
        self,
        month: str,
        supplier_key: str,
        lines: list[Line],
        kind: str = "invoice",
        notes: str = "",
        date: dt.date | None = None,
        recurring_key: str | None = None,
    ) -> Document:
        s = self.suppliers[supplier_key]
        date = date or self._date_in(month)
        cat0 = lines[0].category
        eu = s.country != "DE" and kind == "invoice"
        if eu:  # services from another EU country: reverse charge, no VAT on the invoice
            lines = [Line(x.description, x.net, 0.0, 0, x.category) for x in lines]
            notes = (notes + " " if notes else "") + self.rng.choice(
                [
                    "Reverse charge – Steuerschuldnerschaft des Leistungsempfängers.",
                    "VAT reverse charge applies (Art. 196 VAT Directive).",
                    "Steuerschuldnerschaft des Leistungsempfängers (§ 13b UStG).",
                ]
            )
        net = sum(x.net for x in lines)
        vat = sum(x.vat for x in lines)
        requester = self._requester(cat0)
        doc = Document(
            self._next_id(kind),
            self.id,
            kind,
            s.id,
            s.name,
            s.country,
            s.vat_id,
            self._invoice_number(s, date) if kind == "invoice" else f"POS-{self.rng.randrange(10**6, 10**7)}",
            date.isoformat(),
            (date + dt.timedelta(days=self.rng.choice([14, 30]))).isoformat(),
            s.iban if kind == "invoice" else None,
            requester.id,
            lines,
            net,
            vat,
            net + vat,
            notes,
            month,
            recurring_key=recurring_key,
        )
        self.documents.append(doc)
        return doc

    def _annual(self, month: str, key: str, category: str) -> None:
        rng = self.rng
        start_m, _ = month_bounds(month)
        start = (
            start_m
            if rng.random() > self.world["deferrals"]["mid_month_start"]
            else start_m + dt.timedelta(days=rng.randrange(4, 25))
        )
        end = dt.date(start.year + 1, start.month, start.day) - dt.timedelta(days=1)
        net = rng.randrange(60_000, 2_400_000) if category == "software" else rng.randrange(80_000, 1_800_000)
        templates = [
            "Leistungszeitraum: {s:%d.%m.%Y} – {e:%d.%m.%Y}",
            "Subscription term: {s:%b %d, %Y} to {e:%b %d, %Y}",
            "Jahreslizenz, gültig vom {s:%d.%m.%Y} bis {e:%d.%m.%Y}.",
            "Laufzeit 12 Monate ab dem {s:%d.%m.%Y}",
            "Versicherungsjahr {s:%d.%m.%Y} bis {e:%d.%m.%Y}",
            "Annual plan, billed yearly in advance. Period {s:%Y-%m-%d} – {e:%Y-%m-%d}.",
        ]
        t = rng.choice(templates[4:5] if category == "insurance" else [x for i, x in enumerate(templates) if i != 4])
        doc = self._make(
            month,
            key,
            [self._line(category, net, month=month)],
            notes=t.format(s=start, e=end),
            date=start if start.month == start_m.month else start_m,
        )
        doc.service_start, doc.service_end = start.isoformat(), end.isoformat()

    def month(self, month: str, evaluation: bool) -> None:
        rng = self.rng
        start, end = month_bounds(month)
        # recurring invoices (one may be withheld in an evaluation month: an accrual)
        active = [k for k, r in self.recurring.items() if r["until"] is None or r["until"] >= month]
        withheld = []
        if evaluation:
            candidates = [k for k in active if self.recurring[k]["until"] != month]
            withheld = rng.sample(candidates, min(len(candidates), rng.choice([0, 1, 1, 2])))
        self.missing[month] = withheld
        self.cancelled.setdefault(month, [])
        for k in active:
            r = self.recurring[k]
            if k in withheld:
                continue
            factor = 1.0 if r["category"] == "rent" else rng.uniform(0.85, 1.18)
            net = cents_round(r["base"] * factor)
            notes = f"Leistungszeitraum {start:%m/%Y}"
            if r["until"] == month:
                notes += f". Vertrag gekündigt zum {end:%d.%m.%Y} – dies ist die letzte Rechnung."
            doc = self._make(
                month,
                r["supplier"],
                [self._line(r["category"], net, month=month)],
                notes=notes,
                date=start + dt.timedelta(days=rng.randrange(0, 6)),
                recurring_key=k,
            )
            doc.service_start, doc.service_end = start.isoformat(), end.isoformat()
        # schedule a cancellation for next month's decoy: the last invoice comes this month
        nxt = add_months(month, 1)
        cancellable = [
            k
            for k in active
            if self.recurring[k]["category"] != "rent" and self.recurring[k]["until"] is None and k not in withheld
        ]  # the cancellation is announced on this month's invoice, so it must exist
        if (
            nxt in config.load("world")["months"]["splits"].values()
            and cancellable
            and rng.random() < self.world["cancellations"]
        ):
            k = rng.choice(cancellable)
            self.recurring[k]["until"] = month
            self.cancelled.setdefault(nxt, []).append(k)
            # the invoice already written above for this month gets the note
            for d in reversed(self.documents):
                if d.recurring_key == k and d.month == month:
                    d.notes += f". Vertrag gekündigt zum {end:%d.%m.%Y} – dies ist die letzte Rechnung."
                    break
        # everything else
        cats = [c for c in self.world["categories"] if c not in self.world["recurring_categories"] and c != "breakfast"]
        n = int(self.spec["docs_per_month"] * rng.uniform(0.85, 1.15))
        for _ in range(n):
            cat = rng.choice(cats)
            keys = [k for k, s in self.suppliers.items() if cat in s.categories and (not s.new_in or s.new_in <= month)]
            if not keys:
                continue
            k = rng.choice(keys)
            if cat in ("software", "insurance") and rng.random() < self.world["deferrals"]["annual_share"]:
                self._annual(month, k, cat)
                continue
            kind = (
                "card" if cat in ("rail", "hotel", "meals", "office", "shipping") and rng.random() < 0.6 else "invoice"
            )
            if kind == "card" and self.suppliers[k].country != "DE":
                kind = "invoice"
            lines = []
            if cat == "hotel":
                nights = rng.randrange(1, 4)
                lines.append(self._line("hotel", nights * rng.randrange(8_900, 18_900), month=month))
                if rng.random() < 0.6:
                    lines.append(self._line("breakfast", nights * rng.randrange(1_400, 2_400), month=month))
            else:
                same = [c for c in self.suppliers[k].categories]
                for _j in range(rng.choice([1, 1, 1, 2, 3])):
                    c = rng.choice(same)
                    lo, hi = {
                        "legal": (40_000, 600_000),
                        "marketing": (20_000, 900_000),
                        "training": (15_000, 250_000),
                        "software": (2_000, 60_000),
                        "insurance": (10_000, 90_000),
                    }.get(c, (900, 40_000))
                    lines.append(self._line(c, rng.randrange(lo, hi), month=month, mixed=len(same) > 1))
            notes = ""
            if cat == "software":
                notes = f"Leistungszeitraum {start:%m/%Y}"
            doc = self._make(month, k, lines, kind=kind, notes=notes)
            if cat not in self.world["fixed_cost_centre"] and rng.random() < self.world["noise"]["cost_centre_note"]:
                requester = next(p for p in self.people if p.id == doc.requester)
                other = rng.choice([x for x in self.spec["departments"] if x != requester.department])
                de = {"ENG": "Engineering", "SALES": "Vertrieb", "ADMIN": "Verwaltung", "OPS": "Betrieb"}[other]
                en = {"ENG": "Engineering", "SALES": "Sales", "ADMIN": "Administration", "OPS": "Operations"}[other]
                note = rng.choice(
                    [
                        f"Kostenübernahme durch {de}.",
                        f"Bitte auf Kostenstelle {self.spec['departments'][other]} buchen.",
                        f"Charged to {en}.",
                        f"Für das Team {de} bestellt.",
                    ]
                )
                doc.notes = f"{doc.notes} {note}".strip()
                doc.cc_department = other

    # ------------------------------------------------------------------------------------------ issues

    def plant_issues(self, month: str) -> None:
        rng = self.rng
        conf = self.world["issues"]
        docs = [d for d in self.documents if d.month == month and d.kind == "invoice"]
        for d in list(docs):
            r = rng.random()
            s = next(x for x in self.suppliers.values() if x.id == d.supplier_id)
            if s.country != "DE" and rng.random() < conf["reverse_charge_missing"]:
                d.lines = [Line(x.description, x.net, 0.19, cents_round(x.net * 0.19), x.category) for x in d.lines]
                d.vat_total = sum(x.vat for x in d.lines)
                d.gross_total = d.net_total + d.vat_total
                d.notes = d.notes.split(" Reverse")[0].split(" VAT reverse")[0].split(" Steuerschuldnerschaft")[0]
                self.issues.setdefault(d.id, []).append({"type": "reverse_charge_missing"})
                continue
            if r < conf["duplicate"] and d.recurring_key is None:
                dup = self._make(
                    month,
                    next(k for k, x in self.suppliers.items() if x.id == d.supplier_id),
                    [Line(x.description, x.net, x.vat_rate, x.vat, x.category) for x in d.lines],
                    notes=d.notes,
                    date=min(
                        month_bounds(month)[1], dt.date.fromisoformat(d.date) + dt.timedelta(days=rng.randrange(2, 10))
                    ),
                )
                dup.number = rng.choice(
                    [
                        d.number.replace("-", ""),
                        d.number.replace("-", "/", 1),
                        f" {d.number.lower()}",
                        d.number.replace("RE", "Re."),
                    ]
                )
                dup.requester = rng.choice(self.people).id
                dup.service_start, dup.service_end = d.service_start, d.service_end
                self.issues.setdefault(dup.id, []).append({"type": "duplicate", "of": d.id})
            elif r < conf["duplicate"] + conf["iban_changed"]:
                d.iban = self._iban()
                self.issues.setdefault(d.id, []).append({"type": "iban_changed"})
            elif r < conf["duplicate"] + conf["iban_changed"] + conf["vat_rate_wrong"]:
                std = [i for i, x in enumerate(d.lines) if x.vat_rate == 0.19]
                if std:
                    i = rng.choice(std)
                    x = d.lines[i]
                    d.lines[i] = Line(x.description, x.net, 0.07, cents_round(x.net * 0.07), x.category)
                    d.vat_total = sum(y.vat for y in d.lines)
                    d.gross_total = d.net_total + d.vat_total
                    self.issues.setdefault(d.id, []).append({"type": "vat_rate_wrong", "line": i})
            elif r < conf["duplicate"] + conf["iban_changed"] + conf["vat_rate_wrong"] + conf["arithmetic"]:
                d.gross_total += rng.choice([-1, 1]) * rng.choice([100, 1_000, 900, 10])
                self.issues.setdefault(d.id, []).append({"type": "arithmetic"})
        # decoys
        dec = self.world["decoys"]
        for d in docs:
            if d.id in self.issues or d.kind != "invoice":
                continue
            r = rng.random()
            s = next(x for x in self.suppliers.values() if x.id == d.supplier_id)
            if r < dec["iban_changed_verified"] and not s.iban_changes:
                new = self._iban()
                verified = month_bounds(month)[0].isoformat()  # effective from the first of the month
                s.iban_changes.append({"old": s.iban, "new": new, "verified_at": verified})
                month_invoices = [x for x in self.documents if x.month == month and x.kind == "invoice"]
                for inv in month_invoices:  # every invoice of this supplier this month already uses the new account
                    if inv.supplier_id == s.id and not any(
                        i["type"] == "iban_changed" for i in self.issues.get(inv.id, [])
                    ):
                        inv.iban = new
                        self.decoys.append({"type": "iban_changed_verified", "document": inv.id})
                s.iban = new
        for d in docs:
            if d.recurring_key and d.id not in self.issues and rng.random() < dec["same_amount_new_number"] * 4:
                prev = [x for x in self.documents if x.recurring_key == d.recurring_key and x.month < month]
                if prev:
                    p = max(prev, key=lambda x: x.date)
                    d.lines = [
                        Line(x.description, y.net, x.vat_rate, y.vat, x.category)
                        for x, y in zip(d.lines, p.lines, strict=False)
                    ]
                    d.net_total, d.vat_total, d.gross_total = p.net_total, p.vat_total, p.gross_total
                    self.decoys.append({"type": "same_amount_new_number", "document": d.id, "previous": p.id})
                    break

    # ------------------------------------------------------------------------------------------- truth

    def coding(self, d: Document) -> list[dict]:
        sp = self.spec
        out = []
        requester = next(p for p in self.people if p.id == d.requester)
        change = self.world["habit_changes"].get(self.id)
        for x in d.lines:
            account = sp["habits"].get(x.category, self.world["base_mapping"][x.category])
            if change and x.category == change["category"] and d.month >= change["from"]:
                account = change["account"]
            fixed = self.world["fixed_cost_centre"].get(x.category)
            cc = sp["departments"][fixed or d.cc_department or requester.department]
            if d.supplier_country != "DE" and d.kind == "invoice" and x.vat_rate == 0:
                tax = "RC19"
            else:
                tax = {0.19: "VSt19", 0.07: "VSt7", 0.0: "NONE"}[x.vat_rate]
            out.append({"account": account, "cost_centre": cc, "tax_key": tax})
        return out

    def close(self, month: str) -> dict:
        """Month-end proposals the truth expects: deferrals of prepaid periods, accruals of missing invoices."""
        start, end = month_bounds(month)
        threshold = int(self.spec["materiality_eur"] * 100)
        deferrals = []
        for d in self.documents:
            if (
                d.month != month
                or not d.service_end
                or d.id in {i for i, v in self.issues.items() if any(x["type"] == "duplicate" for x in v)}
            ):
                continue
            s_start, s_end = dt.date.fromisoformat(d.service_start or d.date), dt.date.fromisoformat(d.service_end)
            if s_end <= end or d.net_total < threshold:
                continue
            total_days = (s_end - s_start).days + 1
            future_days = (s_end - max(end, s_start - dt.timedelta(days=1))).days
            coding = self.coding(d)
            # one entry per expense account, in proportion to its lines
            by_account: dict[str, int] = {}
            for x, c in zip(d.lines, coding, strict=True):
                by_account[c["account"]] = by_account.get(c["account"], 0) + x.net
            for acct, net in sorted(by_account.items()):
                amount = cents_round(net * future_days / total_days)
                deferrals.append(
                    {
                        "document": d.id,
                        "debit": "1900",
                        "credit": acct,
                        "amount": amount,
                        "cost_centre": coding[0]["cost_centre"],
                        "period": month,
                        "release_from": add_months(month, 1),
                        "release_until": s_end.isoformat()[:7],
                    }
                )
        accruals = []
        for k in self.missing.get(month, []):
            r = self.recurring[k]
            prev = sorted(
                (x for x in self.documents if x.recurring_key == k and x.month < month), key=lambda x: x.date
            )[-3:]
            if not prev:
                continue
            est = cents_round(sum(x.net_total for x in prev) / len(prev))
            c = self.coding(prev[-1])[0]
            accruals.append(
                {
                    "supplier": self.suppliers[r["supplier"]].id,
                    "debit": c["account"],
                    "credit": "3070",
                    "amount": est,
                    "cost_centre": c["cost_centre"],
                    "period": month,
                    "basis": [x.id for x in prev],
                }
            )
        decoys = [
            {"type": "cancelled_contract", "supplier": self.suppliers[self.recurring[k]["supplier"]].id}
            for k in self.cancelled.get(month, [])
        ]
        return {"deferrals": deferrals, "accruals": accruals, "decoys": decoys}


def build_world() -> list[TenantWorld]:
    world = config.load("world")
    tenants = [TenantWorld(spec, world) for spec in world["tenants"]]
    months = world["months"]["history"] + list(world["months"]["splits"].values())
    evaluation = set(world["months"]["splits"].values())
    for t in tenants:
        for m in months:
            t.month(m, m in evaluation)
            if m in evaluation:
                t.plant_issues(m)
    return tenants
