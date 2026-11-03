"""The agent worker: for each received document, code it and check it; at month end, propose the close.

Orchestrated as LangGraph state graphs so each step is a node with its own trace span, and the route through
the graph (pattern or model, which checks fired) is recorded per document. The worker holds an agent token
for one company: it reads through the ledger API and can only create proposals. Whether anything is booked
or paid is decided by the people who approve.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .. import config
from .checks import Checker, Finding
from .client import Ledger
from .close import CloseResult, close_month
from .coding import CompanyModel, DocumentCoding, ask_model


class DocState(TypedDict, total=False):
    doc: dict
    coding: DocumentCoding
    findings: list[Finding]
    spans: list[dict]


@dataclass
class Context:
    ledger: Ledger
    reference: dict
    model: CompanyModel
    checker: Checker
    month_docs: list[dict]
    use_llm: bool
    threshold: float


def _span(state: DocState, name: str, start: float, **attrs: Any) -> list[dict]:
    return [*state.get("spans", []), {"name": name, "ms": round((time.perf_counter() - start) * 1000, 3), **attrs}]


def build_document_graph(ctx: Context) -> Any:
    def pattern_coding(state: DocState) -> DocState:
        t = time.perf_counter()
        doc = state["doc"]
        dc = DocumentCoding(doc["id"], [ctx.model.code_line(doc, i, x) for i, x in enumerate(doc["lines"])])
        return {
            "coding": dc,
            "spans": _span(state, "pattern_coding", t, uncovered=sum(x.source == "none" for x in dc.lines)),
        }

    def model_coding(state: DocState) -> DocState:
        t = time.perf_counter()
        doc, dc = state["doc"], state["coding"]
        for i, lc in enumerate(dc.lines):
            if lc.source == "none":
                new, cost = ask_model(ctx.model, ctx.reference, doc, i, doc["lines"][i])
                dc.lines[i] = new
                dc.llm_calls += 1
                dc.cost_usd += cost
        return {
            "coding": dc,
            "spans": _span(state, "model_coding", t, llm_calls=dc.llm_calls, cost_usd=round(dc.cost_usd, 6)),
        }

    def checks(state: DocState) -> DocState:
        t = time.perf_counter()
        found = ctx.checker.check(state["doc"], ctx.month_docs)
        return {"findings": found, "spans": _span(state, "checks", t, findings=[f.issue for f in found])}

    def propose(state: DocState) -> DocState:
        t = time.perf_counter()
        doc, dc = state["doc"], state["coding"]
        bucket = dc.bucket(ctx.threshold)
        if dc.complete:
            ctx.ledger.propose(
                "coding",
                {
                    "lines": [
                        {"line_no": x.line_no, "account": x.account, "cost_centre": x.cost_centre, "tax_key": x.tax_key}
                        for x in dc.lines
                    ]
                },
                document_id=doc["id"],
                confidence=dc.confidence,
                reasoning=" ".join(x.reason for x in dc.lines),
                evidence=[
                    {
                        "bucket": bucket,
                        "sources": [x.source for x in dc.lines],
                        "line_confidence": [x.confidence for x in dc.lines],
                    }
                ],
            )
        for f in state.get("findings", []):
            ctx.ledger.propose(
                "check",
                {"issue": f.issue, "detail": f.detail, "line": f.line},
                document_id=doc["id"],
                confidence=1.0,
                reasoning=f.detail,
                evidence=f.evidence,
            )
        return {"spans": _span(state, "propose", t, bucket=bucket)}

    g = StateGraph(DocState)
    g.add_node("pattern_coding", pattern_coding)
    g.add_node("model_coding", model_coding)
    g.add_node("checks", checks)
    g.add_node("propose", propose)
    g.set_entry_point("pattern_coding")
    g.add_conditional_edges(
        "pattern_coding",
        lambda s: "model_coding" if ctx.use_llm and any(x.source == "none" for x in s["coding"].lines) else "checks",
        {"model_coding": "model_coding", "checks": "checks"},
    )
    g.add_edge("model_coding", "checks")
    g.add_edge("checks", "propose")
    g.add_edge("propose", END)
    return g.compile()


@dataclass
class RunResult:
    tenant: str
    documents: int
    traces: list[dict] = field(default_factory=list)
    close: CloseResult | None = None
    llm_calls: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0


def thresholds() -> dict:
    path = config.ROOT / "config" / "thresholds.yaml"
    if not path.exists():
        return {"ready_confidence": 0.75}
    import yaml

    return yaml.safe_load(path.read_text())


def history_with_coding(ledger: Ledger) -> tuple[list[dict], list[dict]]:
    docs: list[dict] = []
    while True:
        page = ledger.get("/api/documents", status="booked", limit=1000, offset=len(docs))
        docs += page
        if len(page) < 1000:
            break
    bookings = ledger.bookings()
    coding: dict[str, dict[int, dict]] = {}
    for b in bookings:
        coding.setdefault(b["document_id"], {})[b["line_no"]] = {
            "account": b["account"],
            "cost_centre": b["cost_centre"],
        }
    for d in docs:
        lines = coding.get(d["id"], {})
        d["coding"] = [lines[i] for i in sorted(lines)]
    return docs, bookings


def run_company(ledger: Ledger, tenant: str, month: str, use_llm: bool = True) -> RunResult:
    t0 = time.perf_counter()
    reference = ledger.reference()
    history, bookings = history_with_coding(ledger)
    model = CompanyModel(bookings, ledger.people(), reference["cost_centres"])
    month_docs = ledger.documents(month, status="received")
    suppliers = {sid: ledger.supplier(sid) for sid in sorted({d["supplier_id"] for d in month_docs})}
    checker = Checker(history, bookings, suppliers)
    ctx = Context(ledger, reference, model, checker, month_docs, use_llm, float(thresholds()["ready_confidence"]))
    graph = build_document_graph(ctx)
    res = RunResult(tenant, len(month_docs))
    codings: dict[str, list[dict]] = {}
    duplicates: set[str] = set()
    for doc in month_docs:
        state = graph.invoke({"doc": doc, "spans": []})
        dc: DocumentCoding = state["coding"]
        res.llm_calls += dc.llm_calls
        res.cost_usd += dc.cost_usd
        if dc.complete:
            codings[doc["id"]] = [{"account": x.account, "cost_centre": x.cost_centre} for x in dc.lines]
        if any(f.issue == "duplicate" for f in state.get("findings", [])):
            duplicates.add(doc["id"])
        res.traces.append(
            {
                "document": doc["id"],
                "bucket": dc.bucket(ctx.threshold),
                "confidence": dc.confidence,
                "spans": state["spans"],
            }
        )
    # month-end close
    t = time.perf_counter()
    cr = close_month(month, month_docs, codings, history, reference["materiality_cents"], duplicates, use_llm)
    for e in cr.entries:
        ledger.propose(
            "journal",
            e.payload(),
            document_id=e.document_id,
            confidence=1.0,
            reasoning=e.reasoning,
            evidence=e.evidence,
        )
    res.close = cr
    res.llm_calls += cr.llm_calls
    res.cost_usd += cr.cost_usd
    res.traces.append(
        {
            "document": None,
            "step": "close",
            "entries": len(cr.entries),
            "ms": round((time.perf_counter() - t) * 1000, 3),
            "periods_by_rules": cr.periods_by_rules,
            "periods_by_model": cr.periods_by_model,
        }
    )
    res.seconds = time.perf_counter() - t0
    return res
