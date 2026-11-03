"""Apply (or roll back) the SQL migrations in cfa/ledger/migrations, and grant the runtime role its rights.

The owner connection runs migrations; the service connects as the runtime role, which may read and write but
never delete, never alter the schema, and is subject to row-level security.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"
RUNTIME_ROLE = "cfa_app"
WRITABLE = ["bookings", "proposals", "journal_entries", "audit_log", "outbox", "supplier_bank_changes"]


def versions() -> list[str]:
    return sorted(p.name.removesuffix(".up.sql") for p in MIGRATIONS.glob("*.up.sql"))


def up(owner_url: str) -> list[str]:
    applied = []
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "create table if not exists schema_migrations (version text primary key, applied_at timestamptz default now())"
        )
        done = {r[0] for r in conn.execute("select version from schema_migrations")}
        for v in versions():
            if v in done:
                continue
            with conn.transaction():
                conn.execute((MIGRATIONS / f"{v}.up.sql").read_text())
                conn.execute("insert into schema_migrations (version) values (%s)", (v,))
            applied.append(v)
    return applied


def down(owner_url: str, to: str | None = None) -> list[str]:
    rolled = []
    with psycopg.connect(owner_url, autocommit=True) as conn:
        conn.execute(
            "create table if not exists schema_migrations (version text primary key, applied_at timestamptz default now())"
        )
        done = [r[0] for r in conn.execute("select version from schema_migrations order by version desc")]
        for v in done:
            if to is not None and v <= to:
                break
            with conn.transaction():
                conn.execute((MIGRATIONS / f"{v}.down.sql").read_text())
                conn.execute("delete from schema_migrations where version = %s", (v,))
            rolled.append(v)
    return rolled


def ensure_runtime_role(owner_url: str, password: str) -> None:
    """Development and CI only; in GCP the runtime identity is a Cloud SQL IAM user created by Terraform."""
    with psycopg.connect(owner_url, autocommit=True) as conn:
        exists = conn.execute("select 1 from pg_roles where rolname = %s", (RUNTIME_ROLE,)).fetchone()
        if not exists:
            with contextlib.suppress(psycopg.errors.DuplicateObject):
                conn.execute(
                    f"create role {RUNTIME_ROLE} login password %s nosuperuser nobypassrls".replace(
                        "%s", "'" + password.replace("'", "''") + "'"
                    )
                )
        grant(conn)
        publisher_pw = os.environ.get("CFA_PUBLISHER_PASSWORD", "cfa_publisher")
        conn.execute(f"alter role cfa_publisher login password {quoted_pw(publisher_pw)}")


def quoted_pw(pw: str) -> str:
    return "'" + pw.replace("'", "''") + "'"


def grant(conn: psycopg.Connection) -> None:
    db = conn.execute("select current_database()").fetchone()[0]  # type: ignore[index]
    conn.execute(f'grant connect on database "{db}" to {RUNTIME_ROLE}')
    conn.execute(f"grant usage on schema public to {RUNTIME_ROLE}")
    conn.execute(f"grant select on all tables in schema public to {RUNTIME_ROLE}")
    conn.execute(f"grant insert, update on {', '.join(WRITABLE)} to {RUNTIME_ROLE}")
    conn.execute(f"grant insert, update (status) on documents to {RUNTIME_ROLE}")
    conn.execute(f"grant usage on all sequences in schema public to {RUNTIME_ROLE}")
    conn.execute(f"revoke all on schema_migrations from {RUNTIME_ROLE}")
