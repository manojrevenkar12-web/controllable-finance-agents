"""The agents' only way into the company's data: the ledger API, with a token that says who they act for."""

from __future__ import annotations

from typing import Any

import httpx


class LedgerError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"{status}: {body}")
        self.status, self.body = status, body


class Ledger:
    def __init__(
        self, token: str, base_url: str = "http://127.0.0.1:8090", transport: httpx.BaseTransport | None = None
    ):
        self.http = httpx.Client(
            base_url=base_url, transport=transport, timeout=30, headers={"Authorization": f"Bearer {token}"}
        )

    @classmethod
    def in_process(cls, token: str) -> Ledger:
        """Same API, same checks, no network: for evaluation runs and tests."""
        from fastapi.testclient import TestClient

        from ..ledger.app import app

        led = cls.__new__(cls)
        led.http = TestClient(app, headers={"Authorization": f"Bearer {token}"})  # type: ignore[assignment]
        return led

    def _ok(self, r: httpx.Response) -> Any:
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = r.text
            raise LedgerError(r.status_code, body)
        return (
            r.json()
            if r.headers.get("content-type", "").startswith(("application/json", "application/problem"))
            else r.text
        )

    def get(self, path: str, **params: Any) -> Any:
        return self._ok(self.http.get(path, params={k: v for k, v in params.items() if v is not None}))

    def post(self, path: str, body: dict) -> Any:
        return self._ok(self.http.post(path, json=body))

    # convenience
    def documents(self, month: str, status: str | None = None) -> list[dict]:
        out: list[dict] = []
        while True:
            page = self.get("/api/documents", month=month, status=status, limit=1000, offset=len(out))
            out += page
            if len(page) < 1000:
                return out

    def reference(self) -> dict:
        return self.get("/api/reference")

    def people(self) -> list[dict]:
        return self.get("/api/people")

    def bookings(self, before: str | None = None, supplier_id: str | None = None, limit: int = 20000) -> list[dict]:
        return self.get("/api/bookings", before=before, supplier_id=supplier_id, limit=limit)

    def supplier(self, supplier_id: str) -> dict:
        return self.get(f"/api/suppliers/{supplier_id}")

    def propose(
        self,
        kind: str,
        payload: dict,
        document_id: str | None = None,
        confidence: float | None = None,
        reasoning: str = "",
        evidence: list[dict] | None = None,
    ) -> str:
        return self.post(
            "/api/proposals",
            {
                "kind": kind,
                "document_id": document_id,
                "payload": payload,
                "confidence": confidence,
                "reasoning": reasoning,
                "evidence": evidence or [],
            },
        )["id"]
