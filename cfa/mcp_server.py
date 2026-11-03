"""MCP tools over the ledger, for AI tools that act for a signed-in person.

The server is started with that person's token (delegated: the person is the subject, the AI tool the actor),
and every tool calls the ledger API with it. So an employee's assistant sees the employee's own expenses and
cannot propose bookings; an accountant's assistant sees the company and can propose, but cannot approve its own
proposals. Nothing here widens access: the ledger decides, and the tools pass on its refusals.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from .agents.client import Ledger, LedgerError


def build_server(token: str, base_url: str = "http://127.0.0.1:8090", ledger: Ledger | None = None) -> MCPServer:
    led = ledger or Ledger(token, base_url)
    server = MCPServer(
        name="cfa-ledger",
        instructions=(
            "Finance data of one company, seen as the signed-in person sees it. Amounts are in cents. "
            "Proposals are suggestions for an accountant to approve; nothing you do here books or pays anything."
        ),
    )

    def call(fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except LedgerError as e:
            return {"error": e.status, "detail": e.body}

    @server.tool(description="Who the tools act for: person, company, role, and the acting tool.")
    def whoami() -> dict:
        return call(led.get, "/api/me")

    @server.tool(description="Documents (invoices, card receipts) of a month the person may see, e.g. month='2026-11'.")
    def list_documents(month: str, status: str | None = None) -> Any:
        return call(led.get, "/api/documents", month=month, status=status, limit=500)

    @server.tool(description="One document with its lines, by id.")
    def get_document(document_id: str) -> Any:
        return call(led.get, f"/api/documents/{document_id}")

    @server.tool(description="A supplier; bank details only for roles allowed to see them.")
    def get_supplier(supplier_id: str) -> Any:
        return call(led.get, f"/api/suppliers/{supplier_id}")

    @server.tool(description="How earlier invoices of a supplier were booked (account, cost centre, tax key).")
    def booking_history(supplier_id: str, limit: int = 20) -> Any:
        return call(led.get, "/api/bookings", supplier_id=supplier_id, limit=limit)

    @server.tool(description="Chart of accounts, cost centres and tax keys of the company.")
    def reference() -> Any:
        return call(led.get, "/api/reference")

    @server.tool(description="Proposals awaiting a decision, optionally of one kind (coding, check, journal).")
    def open_proposals(kind: str | None = None) -> Any:
        return call(led.get, "/api/proposals", status="proposed", kind=kind)

    @server.tool(
        description="Propose a booking for every line of a document: lines=[{line_no, account, cost_centre, tax_key}]. "
        "An accountant decides."
    )
    def propose_coding(document_id: str, lines: list[dict], reasoning: str) -> Any:
        return call(led.propose, "coding", {"lines": lines}, document_id=document_id, reasoning=reasoning)

    @server.tool(description="Propose a month-end journal entry (deferral, accrual or manual). An accountant decides.")
    def propose_journal_entry(
        period: str,
        debit: str,
        credit: str,
        amount_cents: int,
        cost_centre: str,
        text: str,
        entry_type: str = "manual",
        reasoning: str = "",
    ) -> Any:
        return call(
            led.propose,
            "journal",
            {
                "type": entry_type,
                "period": period,
                "debit": debit,
                "credit": credit,
                "amount_cents": amount_cents,
                "cost_centre": cost_centre,
                "text": text,
            },
            reasoning=reasoning,
        )

    return server
