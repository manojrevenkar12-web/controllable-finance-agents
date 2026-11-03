"""Month-end close: the journal entries a careful accountant would propose, each with its arithmetic shown.

Deferrals. An invoice booked this month that pays for a period running past the month end (an annual licence,
an insurance year) is an expense of the months it covers. The part after this month moves to prepaid expenses
(aktive Rechnungsabgrenzung), day by day: amount = net x days after month end / days in the period, rounded
to the cent, per expense account of the invoice. Invoices below the company's materiality threshold are left.

Accruals. A supplier who billed in each of the last three months but has not billed this one (rent, hosting,
telephone) still delivered: accrue the average of the last three net amounts to the account and cost centre of
the latest invoice, unless the latest invoice says the contract ended.

Service periods are read by rules for the usual ways of writing them; a note that mentions dates the rules do
not understand goes to the model. Its answer is used only when both ends are written in the notes (or the start
and a stated length are): the model reads the notes, it never supplies a date.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .. import config
from . import claude_cli

MONTHS_EN = {
    m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}
MONTHS_DE = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}
D = r"(\d{1,2})\.(\d{1,2})\.(\d{4})"
ISO = r"(\d{4})-(\d{2})-(\d{2})"
EN = r"([A-Z][a-z]{2})[a-z]*\.? (\d{1,2}), (\d{4})"
DASH = r"\s*(?:–|-|—|bis|to|until)\s*"


def month_end(month: str) -> dt.date:
    y, m = map(int, month.split("-"))
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def cents_round(x: float) -> int:
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def add_years(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def add_months(d: dt.date, months: int) -> dt.date:
    k = d.year * 12 + d.month - 1 + months
    y, m = divmod(k, 12)
    last = (dt.date(y + (m == 11), (m + 1) % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m + 1, min(d.day, last))


def parse_period(notes: str) -> tuple[dt.date, dt.date] | None:
    """A service period in the ways suppliers usually write it, or None."""
    m = re.search(D + DASH + D, notes)
    if m:
        a = [int(x) for x in m.groups()]
        return dt.date(a[2], a[1], a[0]), dt.date(a[5], a[4], a[3])
    m = re.search(ISO + DASH + ISO, notes)
    if m:
        a = [int(x) for x in m.groups()]
        return dt.date(a[0], a[1], a[2]), dt.date(a[3], a[4], a[5])
    m = re.search(EN + DASH + EN, notes)
    if m and m.group(1).lower()[:3] in MONTHS_EN and m.group(4).lower()[:3] in MONTHS_EN:
        g = m.groups()
        return (
            dt.date(int(g[2]), MONTHS_EN[g[0].lower()[:3]], int(g[1])),
            dt.date(int(g[5]), MONTHS_EN[g[3].lower()[:3]], int(g[4])),
        )
    m = re.search(r"(?:Laufzeit|term|Dauer)\D{0,5}(\d{1,2}) (?:Monate|months)\D{0,12}" + D, notes, re.IGNORECASE)
    if m:
        n, d_, mo, y = (int(x) for x in m.groups())
        start = dt.date(y, mo, d_)
        return start, add_months(start, n) - dt.timedelta(days=1)
    return None


NUMBER_WORDS = {
    w: i
    for i, ws in enumerate(
        [
            ("one", "ein", "eine", "einen"),
            ("two", "zwei"),
            ("three", "drei"),
            ("four", "vier"),
            ("five", "fünf"),
            ("six", "sechs"),
            ("seven", "sieben"),
            ("eight", "acht"),
            ("nine", "neun"),
            ("ten", "zehn"),
            ("eleven", "elf"),
            ("twelve", "zwölf"),
        ],
        1,
    )
    for w in ws
}
MONTH_NAMES = {
    **MONTHS_DE,
    **{k: v for k, v in MONTHS_EN.items()},
    "maerz": 3,
    "mrz": 3,
    "okt": 10,
    "dez": 12,
    "mai": 5,
}


def _month_no(name: str) -> int | None:
    n = name.lower().rstrip(".")
    return MONTH_NAMES.get(n) or MONTH_NAMES.get(n[:3])


def _date(y: int, m: int | None, d: int) -> dt.date | None:
    if m is None:
        return None
    try:
        return dt.date(y + 2000 if y < 100 else y, m, d)
    except ValueError:
        return None


def written_dates(notes: str) -> set[dt.date]:
    """Every calendar date written out in the notes, in German, English or ISO form."""
    found: list[dt.date | None] = []
    for m in re.finditer(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)", notes):
        found.append(_date(int(m[3]), int(m[2]), int(m[1])))
    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", notes):
        found.append(_date(int(m[1]), int(m[2]), int(m[3])))
    for m in re.finditer(r"\b([A-Za-zäÄ]{3,9})\.? (\d{1,2}),? (\d{4})", notes):  # Nov 1, 2026
        found.append(_date(int(m[3]), _month_no(m[1]), int(m[2])))
    for m in re.finditer(r"(?<!\d)(\d{1,2})\.? ([A-Za-zäÄ]{3,9})\.? (\d{4})", notes):  # 1 November 2026, 1. März 2027
        found.append(_date(int(m[3]), _month_no(m[2]), int(m[1])))
    return {d for d in found if d}


def stated_lengths(notes: str) -> set[int]:
    """Lengths in months the notes state: "12 Monate", "24-month", "two-year", "zwei Jahre"."""
    out = set()
    for m in re.finditer(r"\b(\d{1,2}|[a-zäöü]+)[- ]?(month|monat|year|jahr)", notes, re.IGNORECASE):
        n = int(m[1]) if m[1].isdigit() else NUMBER_WORDS.get(m[1].lower())
        if n:
            out.add(n * (12 if m[2].lower() in ("year", "jahr") else 1))
    return out


def stated_in(period: tuple[dt.date, dt.date], notes: str) -> bool:
    """True when the notes write both ends of the period, or its start and a length that ends where it ends."""
    start, stop = period
    dates = written_dates(notes)
    if start not in dates:
        return False
    if stop in dates:
        return True
    return any(add_months(start, n) - dt.timedelta(days=1) == stop for n in stated_lengths(notes))


DATEISH = re.compile(
    r"\d{1,2}\.\d{1,2}\.\d{2,4}|\d{4}-\d{2}-\d{2}|\b(?:19|20)\d{2}\b|monat|month|jahr|year", re.IGNORECASE
)

PERIOD_SCHEMA = {
    "type": "object",
    "properties": {
        "has_period": {"type": "boolean"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "contract_ended": {"type": "boolean"},
        "confidence": {"type": "number"},
    },
    "required": ["has_period", "start", "end", "contract_ended", "confidence"],
}


def ask_period(notes: str, invoice_date: str) -> tuple[tuple[dt.date, dt.date] | None, float]:
    cfg = config.load("agents")["close"]["llm"]
    system = (config.ROOT / cfg["prompt"]).read_text()
    raw, _, _ = claude_cli.ask(
        cfg["model"], system, f"Invoice date: {invoice_date}\nNotes: {notes}", PERIOD_SCHEMA, [], cfg["budget_usd"]
    )
    out = raw.get("structured_output") or {}
    cost = claude_cli.usage(raw)["cost_usd"]
    try:
        if out.get("has_period") and out.get("confidence", 0) >= 0.6:
            a, b = dt.date.fromisoformat(out["start"]), dt.date.fromisoformat(out["end"])
            if a <= b and (b - a).days <= 366 * 5 and stated_in((a, b), notes):
                return (a, b), cost
    except (ValueError, TypeError):
        pass
    return None, cost


@dataclass
class Entry:
    type: str  # deferral | accrual
    period: str
    debit: str
    credit: str
    amount_cents: int
    cost_centre: str
    text: str
    document_id: str | None
    supplier_id: str | None
    reasoning: str
    evidence: list[dict] = field(default_factory=list)

    def payload(self) -> dict:
        return {
            "type": self.type,
            "period": self.period,
            "debit": self.debit,
            "credit": self.credit,
            "amount_cents": self.amount_cents,
            "cost_centre": self.cost_centre,
            "text": self.text,
            "supplier_id": self.supplier_id,
        }


@dataclass
class CloseResult:
    entries: list[Entry]
    llm_calls: int = 0
    cost_usd: float = 0.0
    periods_by_rules: int = 0
    periods_by_model: int = 0


def ended(notes: str) -> bool:
    """True when a clause of the notes says the contract ends, and that clause is not a condition or a notice
    period ("renews automatically unless cancelled", "Kündigungsfrist 3 Monate")."""
    cfg = config.load("agents")["close"]["contract_end"]
    for clause in re.split(r"(?<!\d)[.;!?](?!\d)|\s[–—-]\s", notes):
        low = clause.lower()
        if any(re.search(p, low) for p in cfg["says_ended"]) and not any(re.search(p, low) for p in cfg["unless"]):
            return True
    return False


def close_month(
    month: str,
    documents: list[dict],
    codings: dict[str, list[dict]],
    history: list[dict],
    materiality_cents: int,
    skip: set[str],
    use_llm: bool | None = None,
) -> CloseResult:
    """documents: this month's; codings: document -> lines (account, cost centre) as approved or proposed;
    history: earlier documents with their bookings; skip: documents not to touch (confirmed duplicates)."""
    cfg = config.load("agents")["close"]
    use_llm = cfg["llm"]["enabled"] if use_llm is None else use_llm
    end = month_end(month)
    res = CloseResult([])
    for d in documents:
        if d["id"] in skip or d["id"] not in codings or not d["notes"]:
            continue
        period = parse_period(d["notes"])
        if period:
            res.periods_by_rules += 1
        elif use_llm and DATEISH.search(d["notes"]) and not re.search(r"Leistungszeitraum \d{2}/\d{4}", d["notes"]):
            period, cost = ask_period(d["notes"], d["date"])
            res.llm_calls += 1
            res.cost_usd += cost
            if period:
                res.periods_by_model += 1
        if not period or period[1] <= end or d["net_total"] < materiality_cents:
            continue
        start, stop = period
        total = (stop - start).days + 1
        future = (stop - max(end, start - dt.timedelta(days=1))).days
        by_account: dict[str, int] = {}
        for line, c in zip(d["lines"], codings[d["id"]], strict=True):
            by_account[c["account"]] = by_account.get(c["account"], 0) + line["net"]
        for account, net in sorted(by_account.items()):
            amount = cents_round(net * future / total)
            if amount <= 0:
                continue
            res.entries.append(
                Entry(
                    "deferral",
                    month,
                    cfg["prepaid_account"],
                    account,
                    amount,
                    codings[d["id"]][0]["cost_centre"],
                    f"RAP {d['supplier_name'][:30]} {start:%m/%y}-{stop:%m/%y}",
                    d["id"],
                    d["supplier_id"],
                    f"{net / 100:.2f} EUR for {start:%d.%m.%Y}–{stop:%d.%m.%Y} ({total} days); {future} days fall after "
                    f"{end:%d.%m.%Y}: {net / 100:.2f} × {future}/{total} = {amount / 100:.2f} EUR to prepaid expenses.",
                    [
                        {
                            "document": d["id"],
                            "net": net,
                            "start": start.isoformat(),
                            "end": stop.isoformat(),
                            "days": total,
                            "days_after_month_end": future,
                        }
                    ],
                )
            )
    # accruals
    months = sorted(
        {
            add_months(dt.date(end.year, end.month, 1), -(i + 1)).strftime("%Y-%m")
            for i in range(cfg["recurring_months"])
        }
    )
    billed_now = {d["supplier_id"] for d in documents}
    by_supplier: dict[str, list[dict]] = {}
    for h in history:
        by_supplier.setdefault(h["supplier_id"], []).append(h)
    for supplier, docs in sorted(by_supplier.items()):
        window = sorted((h for h in docs if h["month"] in months), key=lambda h: h["date"])
        billed = {h["month"] for h in window}
        # once a month in the window, allowing one month that was itself missing (and accrued then)
        if (
            supplier in billed_now
            or len(window) != len(billed)
            or len(billed) < len(months) - cfg["recurring_gap_months"]
        ):
            continue
        recent = sorted(docs, key=lambda h: h["date"])[-len(months) :]
        nets = [h["net_total"] for h in recent]
        mean = sum(nets) / len(nets)
        spread = (sum((x - mean) ** 2 for x in nets) / len(nets)) ** 0.5 / mean if mean else 1.0
        days = [int(h["date"][8:10]) for h in recent]
        if spread > cfg["recurring_max_variation"] or max(days) - min(days) > cfg["recurring_max_day_spread"]:
            continue  # bought three months running, but not a subscription
        last = recent[-1]
        if ended(last["notes"]):
            continue
        est = cents_round(sum(h["net_total"] for h in recent) / len(recent))
        c = last["coding"][0]
        res.entries.append(
            Entry(
                "accrual",
                month,
                c["account"],
                cfg["accrual_account"],
                est,
                c["cost_centre"],
                f"Abgrenzung {last['supplier_name'][:30]} {end:%m/%y}",
                None,
                supplier,
                f"billed monthly (last: {', '.join(h['month'] for h in recent)}) but no invoice for {month}; accrue the average "
                f"net {est / 100:.2f} EUR to {c['account']} / cost centre {c['cost_centre']} as on the latest invoice.",
                [{"basis": [h["id"] for h in recent], "nets": [h["net_total"] for h in recent]}],
            )
        )
    return res
