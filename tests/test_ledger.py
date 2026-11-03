"""The ledger keeps the rules agents must not be able to bend: who sees what, four eyes, append-only records."""

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from cfa.ledger.app import app
from cfa.ledger.auth import mint, verify
from tests.conftest import APP

T, OTHER = "t-nordlicht", "t-elbwerk"
pytestmark = pytest.mark.usefixtures("ledger_db")


def client(
    role: str, sub: str | None = None, dept: str | None = None, tenant: str = T, actor: str | None = None
) -> TestClient:
    return TestClient(
        app, headers={"Authorization": "Bearer " + mint(sub or f"{tenant}-{role}", tenant, role, dept, actor)}
    )


def people(c: TestClient) -> list[dict]:
    return c.get("/api/people").json()


def test_who_sees_which_documents():
    acc = client("accountant")
    everyone = acc.get("/api/documents?month=2026-11&limit=1000").json()
    staff = people(acc)
    emp = next(p for p in staff if p["role"] == "employee")
    own = client("employee", emp["id"], emp["department"]).get("/api/documents?month=2026-11&limit=1000").json()
    assert own and all(d["requester"] == emp["id"] for d in own)
    appr = next(p for p in staff if p["role"] == "approver")
    dept_ids = {p["id"] for p in staff if p["department"] == appr["department"]}
    mine = client("approver", appr["id"], appr["department"]).get("/api/documents?month=2026-11&limit=1000").json()
    assert mine and {d["requester"] for d in mine} <= dept_ids and len(mine) < len(everyone)
    other = next(d for d in everyone if d["requester"] != emp["id"])
    assert client("employee", emp["id"], emp["department"]).get(f"/api/documents/{other['id']}").status_code == 404


def test_companies_are_isolated():
    theirs = client("accountant", tenant=OTHER).get("/api/documents?month=2026-11&limit=1").json()[0]
    assert client("admin").get(f"/api/documents/{theirs['id']}").status_code == 404
    assert client("admin").get(f"/api/suppliers/{theirs['supplier_id']}").status_code == 404


def test_bank_details_only_for_finance_roles():
    acc = client("accountant")
    d = acc.get("/api/documents?month=2026-11&status=received&limit=50").json()
    staff = {p["id"]: p for p in people(acc)}
    inv = next(x for x in d if x["kind"] == "invoice" and staff[x["requester"]]["role"] in ("employee", "approver"))
    assert inv["iban"] and acc.get(f"/api/suppliers/{inv['supplier_id']}").json()["iban"]
    emp = staff[inv["requester"]]
    c = client(emp["role"], emp["id"], emp["department"])
    assert c.get(f"/api/documents/{inv['id']}").json()["iban"] is None
    assert c.get(f"/api/suppliers/{inv['supplier_id']}").json()["iban"] is None


def test_roles_limit_actions():
    emp = client("employee", f"{T}-u10", "ENG")
    assert emp.get("/api/bookings").status_code == 403
    assert emp.post("/api/proposals", json={"kind": "check", "document_id": "x", "payload": {}}).status_code == 403
    assert (
        client("agent")
        .post("/api/proposals/00000000-0000-0000-0000-000000000000/decision", json={"decision": "approve"})
        .status_code
        == 403
    )
    assert client("agent").get("/api/exports/datev?period=2026-11").status_code == 403


def _received(c: TestClient) -> dict:
    return c.get("/api/documents?month=2026-11&status=received&limit=1").json()[0]


def test_four_eyes_and_decisions_are_final():
    acc = client("accountant", f"{T}-u05")
    doc = _received(acc)
    lines = [
        {"line_no": i, "account": "6815", "cost_centre": "1000", "tax_key": "VSt19"} for i in range(len(doc["lines"]))
    ]
    pid = acc.post(
        "/api/proposals", json={"kind": "coding", "document_id": doc["id"], "payload": {"lines": lines}}
    ).json()["id"]
    r = acc.post(f"/api/proposals/{pid}/decision", json={"decision": "approve"})
    assert r.status_code == 403 and r.json()["title"] == "Four eyes"
    other = client("accountant", f"{T}-u06")
    assert other.post(f"/api/proposals/{pid}/decision", json={"decision": "approve"}).json()["status"] == "approved"
    assert other.post(f"/api/proposals/{pid}/decision", json={"decision": "reject"}).status_code == 409
    assert acc.get(f"/api/documents/{doc['id']}").json()["status"] == "booked"


def test_validation_of_proposals():
    agent = client("agent")
    doc = _received(agent)
    bad = [{"line_no": 0, "account": "9999", "cost_centre": "1000", "tax_key": "VSt19"}]
    r = agent.post("/api/proposals", json={"kind": "coding", "document_id": doc["id"], "payload": {"lines": bad}})
    assert r.status_code == 422
    assert (
        agent.post(
            "/api/proposals", json={"kind": "check", "document_id": doc["id"], "payload": {"issue": "vibes"}}
        ).status_code
        == 422
    )
    j = {
        "type": "deferral",
        "period": "2026-11",
        "debit": "1900",
        "credit": "6837",
        "amount_cents": -5,
        "cost_centre": "1000",
        "text": "x",
    }
    assert agent.post("/api/proposals", json={"kind": "journal", "payload": j}).status_code == 422


def test_only_approved_entries_reach_the_journal_and_the_export():
    agent, acc = client("agent"), client("accountant", f"{T}-u05")
    base = {"type": "accrual", "period": "2026-11", "debit": "6805", "credit": "3070", "cost_centre": "1000"}
    keep = agent.post(
        "/api/proposals", json={"kind": "journal", "payload": {**base, "amount_cents": 12345, "text": "keep me"}}
    ).json()["id"]
    drop = agent.post(
        "/api/proposals", json={"kind": "journal", "payload": {**base, "amount_cents": 777, "text": "drop me"}}
    ).json()["id"]
    assert acc.post(f"/api/proposals/{keep}/decision", json={"decision": "approve"}).status_code == 200
    assert (
        acc.post(f"/api/proposals/{drop}/decision", json={"decision": "reject", "note": "not needed"}).status_code
        == 200
    )
    texts = [e["text"] for e in acc.get("/api/journal?period=2026-11").json()]
    assert "keep me" in texts and "drop me" not in texts
    csv = acc.get("/api/exports/datev?period=2026-11").text
    head, cols = csv.splitlines()[:2]
    assert head.startswith("EXTF;700;21;Buchungsstapel") and cols.startswith("Umsatz (ohne Soll/Haben-Kz)")
    assert "123,45;S;EUR;6805;3070" in csv and "7,77" not in csv


def test_override_is_validated_and_recorded():
    agent, acc = client("agent"), client("accountant", f"{T}-u05")
    doc = client("accountant").get("/api/documents?month=2026-11&status=received&limit=5").json()[3]
    lines = [
        {"line_no": i, "account": "6815", "cost_centre": "1000", "tax_key": "VSt19"} for i in range(len(doc["lines"]))
    ]
    pid = agent.post(
        "/api/proposals", json={"kind": "coding", "document_id": doc["id"], "payload": {"lines": lines}}
    ).json()["id"]
    bad = acc.post(
        f"/api/proposals/{pid}/decision",
        json={"decision": "override", "payload": {"lines": [{**lines[0], "account": "0000"}]}},
    )
    assert bad.status_code == 422
    fixed = [{**x, "account": "6845"} for x in lines]
    assert (
        acc.post(f"/api/proposals/{pid}/decision", json={"decision": "override", "payload": {"lines": fixed}}).json()[
            "status"
        ]
        == "overridden"
    )
    log = acc.get(f"/api/audit?subject={pid}").json()
    assert [e["action"] for e in log] == ["proposal.overridden", "proposal.created"]


def test_delegated_tokens_are_audited_as_both():
    acc = client("accountant", f"{T}-u05", actor="assistant:claude")
    pid = acc.post(
        "/api/proposals",
        json={
            "kind": "journal",
            "payload": {
                "type": "manual",
                "period": "2026-11",
                "debit": "6815",
                "credit": "3070",
                "amount_cents": 100,
                "cost_centre": "1000",
                "text": "t",
            },
        },
    ).json()["id"]
    entry = client("admin").get(f"/api/audit?subject={pid}").json()[0]
    assert entry["actor"] == f"assistant:claude for {T}-u05"


def test_the_database_holds_the_rules_even_without_the_service():
    with psycopg.connect(APP, autocommit=True) as c:
        assert c.execute("select count(*) from documents").fetchone()[0] == 0  # no tenant set: nothing visible
        c.execute("select set_config('app.tenant_id', %s, false)", (T,))
        assert c.execute("select count(*) from documents where tenant_id = %s", (OTHER,)).fetchone()[0] == 0
        assert c.execute("select count(*) from documents").fetchone()[0] > 0
        for sql in (
            "delete from documents",
            "update audit_log set action = 'x'",
            "delete from journal_entries",
            "drop table documents",
            "update documents set net_total = 1",
        ):
            with pytest.raises(psycopg.Error):
                c.execute(sql)
        decided = c.execute("select id from proposals where status <> 'proposed' limit 1").fetchone()
        with pytest.raises(psycopg.Error):
            c.execute("update proposals set status = 'rejected' where id = %s", decided)
        with pytest.raises(psycopg.Error):  # nobody approves their own proposal, even by SQL
            c.execute(
                "insert into proposals (tenant_id, kind, payload, status, created_by, decided_by, decided_at) "
                "values (%s, 'journal', '{}', 'approved', 'a', 'a', now())",
                (T,),
            )


def test_ingest_only_by_the_capture_pipeline():
    doc = {
        "id": "t-nordlicht-test-1",
        "kind": "invoice",
        "supplier_id": "t-nordlicht-s00",
        "number": "X1",
        "date": "2026-11-20",
        "requester": "t-nordlicht-u00",
        "lines": [{"description": "Storage", "net": 1000, "vat_rate": 0.19, "vat": 190}],
        "net_total": 1000,
        "vat_total": 190,
        "gross_total": 1190,
        "month": "2026-11",
    }
    assert client("agent").post("/api/documents", json=doc).status_code == 403
    ing = client("ingest", "capture")
    assert ing.post("/api/documents", json=doc).status_code == 201
    assert ing.post("/api/documents", json=doc).status_code == 409
    assert (
        ing.post("/api/documents", json={**doc, "id": "t-nordlicht-test-2", "supplier_id": "nope"}).status_code == 422
    )
    events = client("agent").get("/api/events?after=0&limit=1000").json()
    assert any(e["key"] == "t-nordlicht-test-1" and e["topic"] == "document.received" for e in events)


def test_tokens():
    assert TestClient(app).get("/api/me").status_code == 401
    assert TestClient(app, headers={"Authorization": "Bearer nonsense"}).get("/api/me").status_code == 401
    expired = mint("x", T, "admin", minutes=-1)
    with pytest.raises(jwt.ExpiredSignatureError):
        verify(expired)
    with pytest.raises(ValueError):
        mint("x", T, "superuser")


def test_migrations_roll_back_and_forward(ledger_db):
    from cfa.ledger import migrate

    def columns() -> set:
        with psycopg.connect(ledger_db) as c:
            return set(
                c.execute(
                    "select table_name, column_name, data_type from information_schema.columns "
                    "where table_schema = 'public' and table_name <> 'schema_migrations'"
                ).fetchall()
            )

    before = columns()
    # roll back and re-apply in a scratch database, so the seeded data used by other tests stays put
    scratch = ledger_db.rsplit("/", 1)[0] + "/cfa_scratch"
    with psycopg.connect(ledger_db, autocommit=True) as c:
        c.execute("drop database if exists cfa_scratch")
        c.execute("create database cfa_scratch")
    migrate.up(scratch)
    after_up = set(
        psycopg.connect(scratch)
        .execute(
            "select table_name, column_name, data_type from information_schema.columns where table_schema = 'public' "
            "and table_name <> 'schema_migrations'"
        )
        .fetchall()
    )
    assert after_up == before
    migrate.down(scratch)
    assert (
        not psycopg.connect(scratch)
        .execute("select 1 from information_schema.tables where table_name = 'documents'")
        .fetchone()
    )
    migrate.up(scratch)
