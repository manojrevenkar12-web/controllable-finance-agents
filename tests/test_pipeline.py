"""The worker end to end on one company of the dev month, through the real API and database."""

import asyncio
import json

import pytest

from cfa import config
from cfa.agents.client import Ledger
from cfa.agents.pipeline import run_company
from cfa.ledger.auth import mint
from cfa.mcp_server import build_server

pytestmark = pytest.mark.usefixtures("ledger_db")
T = "t-moselwein"


@pytest.fixture(scope="module")
def run():
    return run_company(Ledger.in_process(mint("agent:worker", T, "agent")), T, "2026-11", use_llm=False)


def test_every_document_gets_a_route_and_proposals_are_only_proposals(run):
    assert run.documents > 30 and len([t for t in run.traces if t.get("document")]) == run.documents
    admin = Ledger.in_process(mint("t-moselwein-admin", T, "admin"))
    props = admin.get("/api/proposals", limit=2000)
    assert props and all(p["status"] == "proposed" and p["created_by"] == "agent:worker" for p in props)
    assert admin.get("/api/journal", period="2026-11") == []  # nothing is booked until a person approves
    truth = json.loads((config.DATA / "dev" / "truth.json").read_text())["documents"]
    ready = [p for p in props if p["kind"] == "coding" and p["evidence"][0]["bucket"] == "ready"]
    right = sum(
        all(
            x["account"] == y["account"] and x["cost_centre"] == y["cost_centre"] and x["tax_key"] == y["tax_key"]
            for x, y in zip(p["payload"]["lines"], truth[p["document_id"]]["coding"], strict=True)
        )
        for p in ready
    )
    assert ready and right / len(ready) >= 0.95


def test_traces_name_each_step(run):
    spans = [s["name"] for t in run.traces if t.get("document") for s in t["spans"]]
    assert {"pattern_coding", "checks", "propose"} <= set(spans)


def test_mcp_tools_act_as_the_person_and_no_more(run):
    led = Ledger.in_process(mint(f"{T}-u10", T, "employee", "ENG", actor="assistant:desktop"))
    server = build_server("unused", ledger=led)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert {"list_documents", "propose_coding", "booking_history"} <= names

    def call(name, **args):
        res = asyncio.run(server.call_tool(name, args))
        items = [json.loads(c.text) for c in res.content]
        return (
            items[0] if len(items) == 1 and not name.startswith("list") else items
        )  # lists come back one item per block

    me = call("whoami")
    assert me["sub"] == f"{T}-u10" and me["actor"] == "assistant:desktop"
    docs = call("list_documents", month="2026-11")
    assert all(d["requester"] == f"{T}-u10" for d in docs)
    assert call("booking_history", supplier_id="t-moselwein-s00")["error"] == 403
    assert (
        call(
            "propose_journal_entry",
            period="2026-11",
            debit="6815",
            credit="3070",
            amount_cents=1,
            cost_centre="900",
            text="x",
        )["error"]
        == 403
    )
