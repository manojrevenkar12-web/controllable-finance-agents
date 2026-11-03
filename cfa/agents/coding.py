"""Pre-accounting: propose account, cost centre and tax key for every line, or say that a person should decide.

Each company books in its own way, so the agent learns from that company's approved bookings only (fetched
through the ledger API with the agent's token: another company's data is not reachable). For each line it
looks for the most specific pattern with enough history (this supplier and this item; this item from any
supplier; this supplier) and takes as confidence the lower bound of the share of past bookings that agree,
so ten agreeing bookings count for more than two. Lines no pattern covers go to the model with the company's
chart, its cost centres and the most similar past bookings; the model's answer is always for review.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .. import config
from . import claude_cli

WORD = re.compile(r"[a-zäöüß][a-zäöüß\-]*", re.IGNORECASE)


def item_key(description: str) -> str:
    """The item a line is about: its first word, without counts, positions or 'Pauschale'."""
    m = WORD.search(description.split("(")[0].split("–")[0])
    return m.group(0).lower() if m else description.strip().lower()


def words(text: str) -> set[str]:
    return {w.lower() for w in WORD.findall(text) if len(w) > 2}


def noted_centre(notes: str, centre: dict[str, str]) -> tuple[str, float, str] | None:
    """A note that assigns the document to a cost centre: by its code, or by the department's name."""
    if not notes or not config.load("agents")["coding"].get("read_notes", True):
        return None
    codes = {c: d for d, c in centre.items()}
    for code in sorted(codes, key=len, reverse=True):
        if re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", notes) and re.search(
            r"[Kk]ostenstelle|cost cent", notes
        ):
            return code, 0.95, f"the note names cost centre {code}"
    aliases = config.load("agents")["coding"]["department_aliases"]
    low = notes.lower()
    for dept, names in aliases.items():
        for name in names:
            if re.search(rf"\b{re.escape(name.lower())}\b", low) and dept in centre:
                return centre[dept], 0.85, f"the note assigns it to {name}"
    return None


def wilson_lower(k: float, n: float, z: float) -> float:
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / d)


def tax_key(doc: dict, line: dict) -> str:
    """Read from the invoice as printed: the VAT that may be deducted is the VAT shown."""
    if line["vat_rate"] == 0 and doc["kind"] == "invoice" and doc["supplier_country"] != "DE":
        return "RC19"
    return {0.19: "VSt19", 0.07: "VSt7"}.get(round(float(line["vat_rate"]), 2), "NONE")


@dataclass
class LineCoding:
    line_no: int
    account: str | None
    cost_centre: str | None
    tax_key: str
    confidence: float
    source: str  # pattern | model | none
    reason: str


@dataclass
class DocumentCoding:
    document: str
    lines: list[LineCoding]
    llm_calls: int = 0
    cost_usd: float = 0.0
    evidence: list[dict] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        return min(x.confidence for x in self.lines)

    @property
    def complete(self) -> bool:
        return all(x.account and x.cost_centre for x in self.lines)

    def bucket(self, threshold: float) -> str:
        """ready: confident enough to approve in bulk; review: a suggestion to check; person: nothing to suggest."""
        if not self.complete:
            return "person"
        if all(x.source == "pattern" for x in self.lines) and self.confidence >= threshold:
            return "ready"
        return "review"


class CompanyModel:
    """What one company's approved bookings say about how it books, recent bookings weighing more.

    Companies change how they book (a new account for software from June on), so a booking's weight halves
    every ``half_life_days``; confidence is the Wilson lower bound of the weighted share that agrees, with the
    summed weights as the sample size.
    """

    LEVELS = ("supplier_item", "item", "supplier")

    def __init__(self, bookings: list[dict], people: list[dict], cost_centres: list[dict]):
        cfg = config.load("agents")["coding"]
        self.cfg = cfg
        self.dept = {p["id"]: p["department"] for p in people}
        self.centre = {c["department"]: c["code"] for c in cost_centres}
        self.history = bookings
        as_of = max((dt.date.fromisoformat(b["date"]) for b in bookings), default=dt.date.today())
        self.accounts: dict[str, dict[Any, Counter]] = {k: defaultdict(Counter) for k in self.LEVELS}
        self.centres: dict[str, dict[Any, Counter]] = {k: defaultdict(Counter) for k in self.LEVELS}
        self.follow: dict[str, dict[Any, list[float]]] = {k: defaultdict(lambda: [0.0, 0.0]) for k in self.LEVELS}
        self.raw: dict[str, Counter] = {k: Counter() for k in self.LEVELS}
        for b in bookings:
            w = 0.5 ** ((as_of - dt.date.fromisoformat(b["date"])).days / cfg["half_life_days"])
            item = item_key((b["line"] or {}).get("description", ""))
            noted = noted_centre(b.get("notes") or "", self.centre)
            home = self.centre.get(self.dept.get(b["requester"], ""))
            for level, key in self._keys(b["supplier_id"], item).items():
                self.accounts[level][key][b["account"]] += w
                self.raw[level][key] += 1
                if noted:  # a booking that followed a note says nothing about the usual cost centre
                    continue
                self.centres[level][key][b["cost_centre"]] += w
                f = self.follow[level][key]
                f[0] += w * (b["cost_centre"] == home)
                f[1] += w

    @staticmethod
    def _keys(supplier: str, item: str) -> dict[str, Any]:
        return {"supplier_item": (supplier, item), "item": item, "supplier": supplier}

    def code_line(self, doc: dict, line_no: int, line: dict) -> LineCoding:
        cfg = self.cfg
        z = cfg["wilson_z"]
        item = item_key(line["description"])
        weights = {
            "supplier_item": 1.0,
            "item": cfg["fallbacks"]["item_any_supplier"],
            "supplier": cfg["fallbacks"]["supplier_only"],
        }
        keys = self._keys(doc["supplier_id"], item)
        tk = tax_key(doc, line)
        noted = noted_centre(doc.get("notes") or "", self.centre)
        for level in self.LEVELS:
            if self.raw[level][keys[level]] < cfg["min_history"]:
                continue
            counts = self.accounts[level][keys[level]]
            n = sum(counts.values())
            account, k = counts.most_common(1)[0]
            conf_a = wilson_lower(k, n, z) * weights[level]
            home = self.centre.get(self.dept.get(doc["requester"], ""))
            follows, total = self.follow[level][keys[level]]
            if noted:
                cc, conf_c, how = noted[0], noted[1], noted[2]
            elif home and total and follows / total >= cfg["follows_requester_share"]:
                cc, conf_c, how = home, wilson_lower(follows, total, z) * weights[level], "the requester's department"
            elif total:
                cc, kc = self.centres[level][keys[level]].most_common(1)[0]
                conf_c, how = wilson_lower(kc, total, z) * weights[level], f"usually {cc}"
            else:
                cc, conf_c, how = home or "", 0.3, "the requester's department, without history"
            what = {
                "supplier_item": f"'{item}' from this supplier",
                "item": f"'{item}' from any supplier",
                "supplier": "this supplier",
            }[level]
            reason = (
                f"{k / n:.0%} of {self.raw[level][keys[level]]} earlier bookings of {what} (recent ones weigh more) "
                f"went to {account}; cost centre: {how}."
            )
            return LineCoding(line_no, account, cc or None, tk, round(min(conf_a, conf_c), 4), "pattern", reason)
        return LineCoding(line_no, None, None, tk, 0.0, "none", f"no earlier bookings of '{item}' or this supplier")

    def similar(self, doc: dict, line: dict, k: int) -> list[dict]:
        target = words(line["description"]) | words(doc["supplier_name"])
        scored = []
        for b in self.history:
            desc = (b["line"] or {}).get("description", "")
            s = len(target & (words(desc) | words(b["supplier_name"]))) + (
                2 if b["supplier_id"] == doc["supplier_id"] else 0
            )
            if s:
                scored.append((s, b["date"], b))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)  # most similar, then most recent
        return [
            {
                "supplier": b["supplier_name"],
                "item": (b["line"] or {}).get("description"),
                "account": b["account"],
                "cost_centre": b["cost_centre"],
                "requester_department": self.dept.get(b["requester"]),
            }
            for _, _, b in scored[:k]
        ]


LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "account": {"type": "string"},
        "cost_centre": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
    },
    "required": ["account", "cost_centre", "confidence", "reason"],
}


def ask_model(model: CompanyModel, reference: dict, doc: dict, line_no: int, line: dict) -> tuple[LineCoding, float]:
    cfg = config.load("agents")["coding"]["llm"]
    system = (config.ROOT / cfg["prompt"]).read_text()
    context = {
        "chart_of_accounts": [f"{a['number']} {a['name']}" for a in reference["accounts"]],
        "cost_centres": {c["department"]: c["code"] for c in reference["cost_centres"]},
        "invoice": {
            "supplier": doc["supplier_name"],
            "supplier_country": doc["supplier_country"],
            "kind": doc["kind"],
            "notes": doc["notes"],
            "requester_department": model.dept.get(doc["requester"]),
        },
        "line": {"description": line["description"], "net_eur": line["net"] / 100, "vat_rate": line["vat_rate"]},
        "similar_past_bookings": model.similar(doc, line, cfg["similar_bookings"]),
    }
    user = "Code this invoice line for this company.\n" + json.dumps(context, ensure_ascii=False, indent=1)
    raw, _key, _replayed = claude_cli.ask(cfg["model"], system, user, LLM_SCHEMA, [], cfg["budget_usd"])
    out = raw.get("structured_output") or {}
    cost = claude_cli.usage(raw)["cost_usd"]
    accounts = {a["number"] for a in reference["accounts"]}
    centres = {c["code"] for c in reference["cost_centres"]}
    conf = float(out.get("confidence", 0))
    if out.get("account") not in accounts or out.get("cost_centre") not in centres or conf < cfg["min_confidence"]:
        return LineCoding(
            line_no,
            None,
            None,
            tax_key(doc, line),
            0.0,
            "none",
            "the model was not sure enough; a person should code this line",
        ), cost
    return LineCoding(
        line_no,
        out["account"],
        out["cost_centre"],
        tax_key(doc, line),
        round(conf, 4),
        "model",
        f"model: {out.get('reason', '')}",
    ), cost


def code_document(model: CompanyModel, reference: dict, doc: dict, use_llm: bool | None = None) -> DocumentCoding:
    use_llm = config.load("agents")["coding"]["llm"]["enabled"] if use_llm is None else use_llm
    out = DocumentCoding(doc["id"], [])
    for i, line in enumerate(doc["lines"]):
        lc = model.code_line(doc, i, line)
        if lc.source == "none" and use_llm:
            lc, cost = ask_model(model, reference, doc, i, line)
            out.llm_calls += 1
            out.cost_usd += cost
        out.lines.append(lc)
    return out
