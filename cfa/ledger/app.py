"""The ledger service: documents, suppliers, bookings, proposals, approvals, journal entries, audit, events.

Agents are clients like any other. They read what their token allows, and they can only *propose*: bookings
and journal entries are written when a person with the right role approves, never by the proposer (four eyes,
enforced by the database). Every request runs in a transaction bound to the caller's company, so row-level
security holds even if a query forgets its filter.
"""

from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Literal

import jwt
import psycopg
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field, ValidationError

from .. import config
from .auth import Principal, verify

TAX_KEYS = ("VSt19", "VSt7", "RC19", "NONE")
ISSUES = ("duplicate", "iban_changed", "vat_rate_wrong", "reverse_charge_missing", "arithmetic")

app = FastAPI(
    title="cfa ledger",
    version="1.0.0",
    description="System of record behind the finance agents: they read and propose; people approve.",
)
_pool: ConnectionPool[Any] | None = None


def app_url() -> str:
    db = config.load("ledger")["database"]
    return os.environ.get(db["app_url_env"], db["default_app_url"])


def pool() -> ConnectionPool[Any]:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(app_url(), min_size=1, max_size=8, open=True, kwargs={"row_factory": dict_row})
    return _pool


def reset_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
    _pool = None


class Problem(Exception):
    def __init__(self, status: int, title: str, detail: str = ""):
        self.status, self.title, self.detail = status, title, detail


@app.exception_handler(Problem)
def _problem(_: Request, e: Problem) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": e.title, "status": e.status, "detail": e.detail},
        status_code=e.status,
        media_type="application/problem+json",
    )


@app.exception_handler(ValidationError)
def _invalid(_: Request, e: ValidationError) -> JSONResponse:
    return JSONResponse(
        {
            "type": "about:blank",
            "title": "Invalid proposal",
            "status": 422,
            "detail": "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()),
        },
        status_code=422,
        media_type="application/problem+json",
    )


def principal(authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise Problem(401, "Sign-in required")
    try:
        return verify(authorization.removeprefix("Bearer "))
    except jwt.PyJWTError as e:
        raise Problem(401, "Invalid token", str(e)) from None


Caller = Annotated[Principal, Depends(principal)]


def allowed(p: Principal, permission: str) -> bool:
    rule = config.load("ledger")["permissions"][permission]
    return p.role in rule


def require(p: Principal, permission: str) -> None:
    if not allowed(p, permission):
        raise Problem(403, "Not allowed", f"{p.role} may not {permission.replace('_', ' ')}")


@contextmanager
def tx(p: Principal) -> Iterator[psycopg.Connection[Any]]:
    with pool().connection() as conn, conn.transaction():
        conn.execute("select set_config('app.tenant_id', %s, true)", (p.tenant,))
        yield conn


def audit(conn: psycopg.Connection[Any], p: Principal, action: str, subject: str, detail: dict | None = None) -> None:
    conn.execute(
        "insert into audit_log (tenant_id, actor, action, subject, detail) values (%s, %s, %s, %s, %s)",
        (p.tenant, p.audit_name, action, subject, Jsonb(detail or {})),
    )


def emit(conn: psycopg.Connection[Any], p: Principal, event: str, key: str, payload: dict) -> None:
    conn.execute(
        "insert into outbox (tenant_id, topic, key, payload) values (%s, %s, %s, %s)",
        (p.tenant, event, key, Jsonb({"event": event, **payload})),
    )


# ------------------------------------------------------------------------------------------- visibility


def document_scope(p: Principal) -> tuple[str, list[Any]]:
    """The SQL condition limiting which documents a caller may see (within their company, by RLS)."""
    rule = config.load("ledger")["permissions"]["read_documents"].get(p.role)
    if rule == "all":
        return "true", []
    if rule == "own":
        return "d.requester_id = %s", [p.sub]
    if rule == "department":
        return "d.requester_id in (select id from people where department = %s)", [p.department or ""]
    return "false", []


DOC_COLUMNS = (
    "d.id, d.kind, d.supplier_id, s.name as supplier_name, s.country as supplier_country, "
    "s.vat_id as supplier_vat_id, d.number, d.doc_date::text as date, d.due_date::text as due_date, d.iban, "
    "d.requester_id as requester, d.net_total, d.vat_total, d.gross_total, d.notes, d.lines, d.month, d.status"
)


def _doc_out(p: Principal, row: dict) -> dict:
    if not allowed(p, "read_bank_details"):
        row["iban"] = None
    return row


# ---------------------------------------------------------------------------------------------- reading


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/me")
def me(p: Caller) -> dict:
    return {"sub": p.sub, "tenant": p.tenant, "role": p.role, "department": p.department, "actor": p.actor}


@app.get("/api/reference")
def reference(p: Caller) -> dict:
    with tx(p) as c:
        accounts = c.execute("select number, name from accounts order by number").fetchall()
        centres = c.execute("select department, code from cost_centres order by code").fetchall()
        t = c.execute("select name, materiality_cents from tenants").fetchone()
    return {
        "company": t["name"] if t else None,
        "materiality_cents": t["materiality_cents"] if t else None,
        "accounts": accounts,
        "cost_centres": centres,
        "tax_keys": list(TAX_KEYS),
    }


@app.get("/api/documents")
def list_documents(
    p: Caller,
    month: str | None = None,
    status: str | None = None,
    supplier_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict]:
    cond, args = document_scope(p)
    sql = f"select {DOC_COLUMNS} from documents d join suppliers s on s.id = d.supplier_id where {cond}"
    for col, val in (("d.month", month), ("d.status", status), ("d.supplier_id", supplier_id)):
        if val is not None:
            sql += f" and {col} = %s"
            args.append(val)
    sql += " order by d.doc_date, d.id limit %s offset %s"
    with tx(p) as c:
        return [_doc_out(p, r) for r in c.execute(sql, [*args, limit, offset]).fetchall()]


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str, p: Caller) -> dict:
    cond, args = document_scope(p)
    with tx(p) as c:
        row = c.execute(
            f"select {DOC_COLUMNS} from documents d join suppliers s on s.id = d.supplier_id "
            f"where d.id = %s and {cond}",
            [doc_id, *args],
        ).fetchone()
    if not row:
        raise Problem(404, "No such document")  # not 403: a hidden document does not exist for this caller
    return _doc_out(p, row)


@app.get("/api/suppliers/{supplier_id}")
def get_supplier(supplier_id: str, p: Caller) -> dict:
    with tx(p) as c:
        s = c.execute("select id, name, country, vat_id, iban from suppliers where id = %s", (supplier_id,)).fetchone()
        if not s:
            raise Problem(404, "No such supplier")
        if allowed(p, "read_bank_details"):
            s["bank_changes"] = c.execute(
                "select old_iban, new_iban, verified_at::text, verified_by from supplier_bank_changes "
                "where supplier_id = %s order by verified_at",
                (supplier_id,),
            ).fetchall()
        else:
            s["iban"] = None
    return s


@app.get("/api/bookings")
def bookings(
    p: Caller,
    supplier_id: str | None = None,
    before: str | None = None,
    limit: Annotated[int, Query(ge=1, le=20000)] = 500,
) -> list[dict]:
    """Coded history: each booked line with what was booked, for learning a company's habits."""
    require(p, "read_bookings")
    sql = (
        "select b.document_id, b.line_no, d.supplier_id, s.name as supplier_name, s.country as supplier_country, "
        "d.kind, d.doc_date::text as date, d.requester_id as requester, d.lines -> b.line_no as line, "
        "b.account, b.cost_centre, b.tax_key, d.notes, d.net_total, d.month "
        "from bookings b join documents d on d.id = b.document_id join suppliers s on s.id = d.supplier_id where true"
    )
    args: list[Any] = []
    if supplier_id:
        sql += " and d.supplier_id = %s"
        args.append(supplier_id)
    if before:
        sql += " and d.doc_date < %s"
        args.append(before)
    sql += " order by d.doc_date desc, b.document_id, b.line_no limit %s"
    with tx(p) as c:
        return c.execute(sql, [*args, limit]).fetchall()


@app.get("/api/people")
def list_people(p: Caller) -> list[dict]:
    """Names, departments and roles within the company (no contact details)."""
    with tx(p) as c:
        return c.execute("select id, name, department, role from people order by id").fetchall()


@app.get("/api/people/{person_id}")
def get_person(person_id: str, p: Caller) -> dict:
    with tx(p) as c:
        row = c.execute("select id, name, department, role from people where id = %s", (person_id,)).fetchone()
    if not row:
        raise Problem(404, "No such person")
    return row


# ------------------------------------------------------------------------------------------- ingesting


class LineIn(BaseModel):
    description: str
    net: int
    vat_rate: float
    vat: int


class DocumentIn(BaseModel):
    id: str
    kind: Literal["invoice", "card"]
    supplier_id: str
    number: str
    date: str
    due_date: str | None = None
    iban: str | None = None
    requester: str
    lines: list[LineIn] = Field(min_length=1)
    net_total: int
    vat_total: int
    gross_total: int
    notes: str = ""
    month: str


@app.post("/api/documents", status_code=201)
def ingest(doc: DocumentIn, p: Caller) -> dict:
    require(p, "ingest_documents")
    with tx(p) as c:
        try:
            c.execute(
                "insert into documents (id, tenant_id, kind, supplier_id, number, doc_date, due_date, iban, requester_id, "
                "net_total, vat_total, gross_total, notes, lines, month) values "
                "(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    doc.id,
                    p.tenant,
                    doc.kind,
                    doc.supplier_id,
                    doc.number,
                    doc.date,
                    doc.due_date,
                    doc.iban,
                    doc.requester,
                    doc.net_total,
                    doc.vat_total,
                    doc.gross_total,
                    doc.notes,
                    Jsonb([x.model_dump() for x in doc.lines]),
                    doc.month,
                ),
            )
        except psycopg.errors.UniqueViolation:
            raise Problem(409, "Document already received", doc.id) from None
        except psycopg.errors.ForeignKeyViolation as e:
            raise Problem(422, "Unknown supplier or requester", str(e).splitlines()[0]) from None
        emit(c, p, "document.received", doc.id, {"document": doc.id, "month": doc.month})
        audit(c, p, "document.received", doc.id)
    return {"id": doc.id}


# ------------------------------------------------------------------------------------------- proposals


class CodingLine(BaseModel):
    line_no: int = Field(ge=0)
    account: str
    cost_centre: str
    tax_key: Literal["VSt19", "VSt7", "RC19", "NONE"]


class JournalPayload(BaseModel):
    type: Literal["deferral", "accrual", "manual"]
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    debit: str
    credit: str
    amount_cents: int = Field(gt=0)
    cost_centre: str
    text: str = Field(min_length=1, max_length=60)
    supplier_id: str | None = None


class ProposalIn(BaseModel):
    kind: Literal["coding", "check", "journal"]
    document_id: str | None = None
    payload: dict
    confidence: float | None = Field(default=None, ge=0, le=1)
    reasoning: str = ""
    evidence: list[dict] = Field(default_factory=list)


def _validate(c: psycopg.Connection[Any], p: Principal, body: ProposalIn) -> dict:
    doc: dict[str, Any] = {}
    accounts = {r["number"] for r in c.execute("select number from accounts").fetchall()}
    centres = {r["code"] for r in c.execute("select code from cost_centres").fetchall()}
    if body.kind != "journal" or body.document_id:
        cond, args = document_scope(p)
        doc = (
            c.execute(
                f"select d.id, d.lines from documents d where d.id = %s and {cond}", [body.document_id, *args]
            ).fetchone()
            or {}
        )
        if not doc:
            raise Problem(404, "No such document")
    if body.kind == "coding":
        lines = [CodingLine.model_validate(x) for x in body.payload.get("lines", [])]
        if sorted(x.line_no for x in lines) != list(range(len(doc["lines"]))):
            raise Problem(422, "Coding must cover every line once", f"{len(doc['lines'])} lines")
        for x in lines:
            if x.account not in accounts or x.cost_centre not in centres:
                raise Problem(422, "Unknown account or cost centre", f"{x.account} / {x.cost_centre}")
        return {"lines": [x.model_dump() for x in sorted(lines, key=lambda x: x.line_no)]}
    if body.kind == "check":
        if body.payload.get("issue") not in ISSUES:
            raise Problem(422, "Unknown issue", str(body.payload.get("issue")))
        return body.payload
    j = JournalPayload.model_validate(body.payload)
    if j.debit not in accounts or j.credit not in accounts or j.cost_centre not in centres:
        raise Problem(422, "Unknown account or cost centre")
    return j.model_dump()


@app.post("/api/proposals", status_code=201)
def create_proposal(body: ProposalIn, p: Caller) -> dict:
    require(p, "create_proposal")
    with tx(p) as c:
        payload = _validate(c, p, body)
        if (
            body.kind == "coding"
            and c.execute(
                "select 1 from proposals where document_id = %s and kind = 'coding' and status = 'proposed'",
                (body.document_id,),
            ).fetchone()
        ):
            raise Problem(409, "An open coding proposal exists for this document")
        row = c.execute(
            "insert into proposals (tenant_id, kind, document_id, payload, confidence, reasoning, evidence, created_by) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s) returning id::text",
            (
                p.tenant,
                body.kind,
                body.document_id,
                Jsonb(payload),
                body.confidence,
                body.reasoning,
                Jsonb(body.evidence),
                p.audit_name,
            ),
        ).fetchone()
        pid = row["id"]  # type: ignore[index]
        emit(c, p, "proposal.created", pid, {"proposal": pid, "kind": body.kind, "document": body.document_id})
        audit(
            c,
            p,
            "proposal.created",
            pid,
            {"kind": body.kind, "document": body.document_id, "confidence": body.confidence},
        )
    return {"id": pid}


@app.get("/api/proposals")
def list_proposals(
    p: Caller,
    status: str | None = None,
    kind: str | None = None,
    document_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> list[dict]:
    if not (allowed(p, "create_proposal") or allowed(p, "decide_proposal")):
        raise Problem(403, "Not allowed")
    sql = (
        "select id::text, kind, document_id, payload, confidence::float, reasoning, evidence, status, created_by, "
        "created_at::text, decided_by, decided_at::text, decision_note, final_payload from proposals where true"
    )
    args: list[Any] = []
    for col, val in (("status", status), ("kind", kind), ("document_id", document_id)):
        if val is not None:
            sql += f" and {col} = %s"
            args.append(val)
    sql += " order by created_at, id limit %s"
    with tx(p) as c:
        return c.execute(sql, [*args, limit]).fetchall()


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "override"]
    note: str = Field(default="", max_length=2000)
    payload: dict | None = None  # the corrected proposal, for override


@app.post("/api/proposals/{proposal_id}/decision")
def decide(proposal_id: str, body: DecisionIn, p: Caller) -> dict:
    require(p, "decide_proposal")
    with tx(p) as c:
        prop = c.execute(
            "select id::text, kind, document_id, payload, status, created_by from proposals where id = %s for update",
            (proposal_id,),
        ).fetchone()
        if not prop:
            raise Problem(404, "No such proposal")
        if prop["status"] != "proposed":
            raise Problem(409, "Already decided", prop["status"])
        if prop["created_by"] in (p.sub, p.audit_name):
            raise Problem(403, "Four eyes", "nobody approves their own proposal")
        final = prop["payload"]
        if body.decision == "override":
            if body.payload is None:
                raise Problem(422, "An override needs the corrected proposal")
            final = _validate(
                c, p, ProposalIn(kind=prop["kind"], document_id=prop["document_id"], payload=body.payload)
            )
        status = {"approve": "approved", "reject": "rejected", "override": "overridden"}[body.decision]
        c.execute(
            "update proposals set status = %s, decided_by = %s, decided_at = now(), decision_note = %s, final_payload = %s "
            "where id = %s",
            (status, p.audit_name, body.note, Jsonb(final) if status != "rejected" else None, proposal_id),
        )
        effect: dict[str, Any] = {}
        if status != "rejected":
            if prop["kind"] == "coding":
                for x in final["lines"]:
                    c.execute(
                        "insert into bookings (document_id, line_no, tenant_id, account, cost_centre, tax_key, booked_by) "
                        "values (%s, %s, %s, %s, %s, %s, %s)",
                        (
                            prop["document_id"],
                            x["line_no"],
                            p.tenant,
                            x["account"],
                            x["cost_centre"],
                            x["tax_key"],
                            p.audit_name,
                        ),
                    )
                c.execute(
                    "update documents set status = 'booked' where id = %s and status = 'received'",
                    (prop["document_id"],),
                )
                effect = {"booked_lines": len(final["lines"])}
            elif prop["kind"] == "check":
                c.execute("update documents set status = 'on_hold' where id = %s", (prop["document_id"],))
                effect = {"payment": "on hold"}
            else:
                row = c.execute(
                    "insert into journal_entries (tenant_id, period, debit, credit, amount_cents, cost_centre, text, "
                    "document_id, proposal_id, posted_by) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
                    (
                        p.tenant,
                        final["period"],
                        final["debit"],
                        final["credit"],
                        final["amount_cents"],
                        final["cost_centre"],
                        final["text"],
                        prop["document_id"],
                        proposal_id,
                        p.audit_name,
                    ),
                ).fetchone()
                effect = {"journal_entry": row["id"]}  # type: ignore[index]
                emit(c, p, "journal.posted", str(row["id"]), {"proposal": proposal_id, **final})  # type: ignore[index]
        emit(c, p, "proposal.decided", proposal_id, {"proposal": proposal_id, "status": status, "kind": prop["kind"]})
        audit(c, p, f"proposal.{status}", proposal_id, {"kind": prop["kind"], "note": body.note, **effect})
    return {"id": proposal_id, "status": status, **effect}


# ------------------------------------------------------------------------------------- journal, export


@app.get("/api/journal")
def journal(p: Caller, period: str | None = None) -> list[dict]:
    require(p, "read_journal")
    sql = (
        "select id, period, debit, credit, amount_cents, cost_centre, text, document_id, proposal_id::text, posted_by, "
        "posted_at::text from journal_entries"
    )
    args = []
    if period:
        sql += " where period = %s"
        args.append(period)
    with tx(p) as c:
        return c.execute(sql + " order by id", args).fetchall()


def _de_amount(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d}"


@app.get("/api/exports/datev", response_class=PlainTextResponse)
def datev(p: Caller, period: Annotated[str, Query(pattern=r"^\d{4}-\d{2}$")]) -> str:
    """Approved bookings and journal entries of a period as a DATEV-style Buchungsstapel (EXTF, leading columns).

    Only what a person approved appears here: open or rejected proposals never reach the export.
    """
    require(p, "export")
    h = config.load("ledger")["datev"]["header"]
    with tx(p) as c:
        keys = c.execute("select datev_tax_keys from tenants").fetchone()["datev_tax_keys"]  # type: ignore[index]
        lines = c.execute(
            "select b.document_id, b.line_no, b.account, b.cost_centre, b.tax_key, d.doc_date, d.number, d.lines -> b.line_no as line "
            "from bookings b join documents d on d.id = b.document_id where d.month = %s order by d.doc_date, b.document_id, b.line_no",
            (period,),
        ).fetchall()
        entries = c.execute(
            "select id, debit, credit, amount_cents, cost_centre, text, period from journal_entries where period = %s "
            "order by id",
            (period,),
        ).fetchall()
        audit(c, p, "export.datev", period, {"lines": len(lines), "entries": len(entries)})
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    w.writerow(
        [
            "EXTF",
            h["format_version"],
            h["category"],
            h["name"],
            h["version"],
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            f"{period.replace('-', '')}01",
            h["account_length"],
        ]
    )
    w.writerow(
        [
            "Umsatz (ohne Soll/Haben-Kz)",
            "Soll/Haben-Kennzeichen",
            "WKZ Umsatz",
            "Konto",
            "Gegenkonto (ohne BU-Schlüssel)",
            "BU-Schlüssel",
            "Belegdatum",
            "Belegfeld 1",
            "Buchungstext",
            "KOST1 - Kostenstelle",
        ]
    )
    for x in lines:
        gross = int(x["line"]["net"]) + int(x["line"]["vat"])
        w.writerow(
            [
                _de_amount(gross),
                "S",
                "EUR",
                x["account"],
                "3300",
                keys.get(x["tax_key"], ""),
                x["doc_date"].strftime("%d%m"),
                x["number"].strip()[:36],
                str(x["line"]["description"])[:60],
                x["cost_centre"],
            ]
        )
    last_day = {
        "01": 31,
        "02": 28,
        "03": 31,
        "04": 30,
        "05": 31,
        "06": 30,
        "07": 31,
        "08": 31,
        "09": 30,
        "10": 31,
        "11": 30,
        "12": 31,
    }
    for e in entries:
        w.writerow(
            [
                _de_amount(e["amount_cents"]),
                "S",
                "EUR",
                e["debit"],
                e["credit"],
                "",
                f"{last_day[period[5:]]:02d}{period[5:]}",
                f"JE-{e['id']}",
                e["text"][:60],
                e["cost_centre"],
            ]
        )
    return out.getvalue()


# ----------------------------------------------------------------------------------------- events, audit


@app.get("/api/events")
def events(
    p: Caller, after: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=1000)] = 200
) -> list[dict]:
    """The outbox as a feed: the same events the publisher sends to Kafka, for consumers that poll."""
    require(p, "read_events")
    with tx(p) as c:
        return c.execute(
            "select id, topic, key, payload, created_at::text from outbox where id > %s order by id limit %s",
            (after, limit),
        ).fetchall()


@app.get("/api/audit")
def audit_log(p: Caller, subject: str | None = None, limit: Annotated[int, Query(ge=1, le=2000)] = 200) -> list[dict]:
    require(p, "read_audit")
    sql = "select id, actor, action, subject, detail, at::text from audit_log"
    args: list[Any] = []
    if subject:
        sql += " where subject = %s"
        args.append(subject)
    with tx(p) as c:
        return c.execute(sql + " order by id desc limit %s", [*args, limit]).fetchall()


def dumps(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, default=str)
