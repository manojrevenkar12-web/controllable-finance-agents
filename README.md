# Controllable finance agents

Finance AI agents for a German mid-sized company: **coding** (account, cost centre and tax key), **pre-payment
checks**, and the **month-end close** (deferrals and accruals). They are built into a ledger backend, so the AI
prepares the work and an accountant decides. Every proposal carries its reasoning and evidence. Uncertain cases go
to a person. Overrides are one click. Every decision ends up in an append-only audit log.

![The review console: bookings ready to approve in bulk, each with the reason it was proposed](docs/img/inbox.png)

## What it does

| Agent | Proposes | Decided by | Explains with |
|---|---|---|---|
| Coding | account, cost centre and tax key for each line of an invoice or receipt | per-company booking patterns, weighted by recency; cost-centre notes on the invoice; the model only for lines with no pattern | "93 % of 19 earlier bookings of 'flexpreis' from this supplier went to 6650" |
| Checks | hold a payment: duplicate, changed bank details, wrong VAT rate, missing reverse charge, arithmetic | rules over the supplier master and booking history | the earlier invoice, the IBAN on file for the invoice date, the VAT history |
| Close | deferrals (day-based, above materiality) and accruals for monthly suppliers that have not billed | rules; the model reads service periods the rules cannot, and its answer is used only if both dates are written in the notes | the arithmetic: "3.650,00 × 346/365 = 3.460,00 EUR to prepaid expenses" |

Coding sorts documents into three buckets:

- **ready to approve in bulk**: confidence above a threshold calibrated on dev for 99 % precision;
- **needs a look**;
- **for a person**: no pattern and no confident model answer.

The ledger exports approved journal entries as a DATEV (EXTF-style) batch.

## Results

All results are on synthetic companies (10 companies, 30 suppliers, 12 months of history). See
[docs/EVALUATION.md](docs/EVALUATION.md) for the splits, the calibration, and **what has been studied**.

| | test month, release gate (studied after its first run) | held-out month (run once, not studied) |
|---|---|---|
| Documents | 663 | 670 |
| Approved in bulk: share of documents | 62.9 % | 60.7 % |
| Approved in bulk: booked exactly right | 98.1 % | 98.5 % |
| All documents booked exactly right | 95.0 % | 96.6 % |
| Payment issues caught | 97.8 %, no false alarms on verified bank changes | 95.6 %, no false alarms |
| Deferrals found | 54 / 54 | 69 / 69 |
| Accruals found | 7 / 7 | 7 / 8 (**fails** the 0.9 gate) |
| Model calls, cost | 34, $0.035 | 51, $0.044 |

Three candidate versions are evaluated on test and **refused by the gates**: one ignores recency, one ignores
cost-centre notes, one checks bank details against earlier invoices instead of the verified master. CI checks
that they stay refused.

The payment checks have passed every blind case so far (59 / 59). The close agent is the weak spot: service periods
and contract ends written in wordings nobody anticipated. In blind-2 it missed some periods and read four new
phrasings of an ended contract as still running, so it proposed accruals that should not exist. Those are reported
here, not fixed against the set.

Blind case sets were written by an author who saw only [the contract](docs/AGENT_BEHAVIOUR.md) and
[the writing guide](heldout/WRITING_CASES.md), never the code:

| Set | First run (kept, never rewritten) | Now |
|---|---|---|
| blind-1 | 54 / 57 (checks 29 / 29, close 25 / 28) | studied, fixed, regression set: 57 / 57 ([what changed](heldout/blind-1/STUDIED.md)) |
| blind-2 | 53 / 60 (checks 30 / 30, close 23 / 30) | blind: not studied, nothing changed for it |

## Controls

The controls live in the database and the API, not in the prompt.

- **Four eyes.** A proposal cannot be decided by its creator: a `CHECK (decided_by <> created_by)` constraint
  enforces it. Decided proposals are immutable (trigger).
- **Tenancy and least privilege.**
  - Each request runs in a transaction with `app.tenant_id` set, under forced row-level security.
  - The runtime role `cfa_app` can neither delete rows nor change the schema.
  - The outbox publisher has its own role, which sees only the outbox.
- **Who sees what.**
  - Permissions are a matrix by role, in `config/ledger.yaml`.
  - Employees see their own expenses.
  - Bank details are visible only to roles that pay.
- **Append-only.** Journal entries and the audit log refuse `UPDATE` and `DELETE`.
- **Delegation.** Tokens carry an RFC 8693 `act` claim. When an assistant acts for a person, the ledger records
  both, and the MCP server can never do more than that person can.
- **Events.** A transactional outbox in the same transaction as the decision feeds a Kafka publisher (ordered,
  at-least-once delivery).

## Architecture

```mermaid
flowchart LR
  subgraph Agents["cfa/agents (LangGraph, per document)"]
    P[pattern coding] -->|no pattern| M[model coding]
    P --> C[checks]
    M --> C
    C --> PR[propose]
    CL[close agent]
  end
  PR -->|POST /api/proposals| L
  CL -->|POST /api/proposals| L
  subgraph L["Ledger API (FastAPI)"]
    A[auth: JWT + act claim] --> DB[(PostgreSQL 16: RLS, four-eyes, append-only)]
  end
  DB --> O[outbox] --> K[Kafka]
  UI[Review console: React] -->|decisions| L
  MCP[MCP server: tools act as the person] --> L
  L --> X[DATEV export]
```

- `cfa/ledger`: the API, migrations (up and down), roles, auth, seed, and the outbox publisher.
- `cfa/agents`: the coding model, checks, close, the LangGraph pipeline, and the cached Claude CLI client.
- `cfa/mcp_server.py`: MCP tools over the ledger for AI tools that act for a signed-in person.
- `cfa/evals`: scoring with bootstrap intervals, calibration, gates, and held-out sets.
- `cfa/sim`: the synthetic world. Only the evals read its truth.
- `web/`: the review console (React 19, TanStack Query, Motion), tested with Playwright and axe.
- `infra/`: Terraform for GCP: Cloud SQL (private IP, IAM auth), Managed Kafka, Cloud Run service and jobs, Secret
  Manager, BigQuery. It is validated in CI and has **not been applied**.

Close and quality screens:

![Close: each entry shows its arithmetic](docs/img/close.png)
![Agent quality: release decisions by gate](docs/img/quality.png)

## Running it

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
export CFA_OWNER_URL=postgresql://postgres@127.0.0.1:5432/cfa CFA_APP_URL=postgresql://cfa_app:cfa_app@127.0.0.1:5432/cfa
cfa build                 # generate the synthetic world
cfa migrate && cfa seed dev
cfa run dev               # agents propose for every company's month
cfa serve                 # API + console on :8090 (build the console first: cd web && pnpm i && pnpm build)
cfa release production    # evaluate on test and apply the gates
cfa heldout blind-2       # run a blind case set (first run kept)
pytest -q                 # 47 tests; ledger tests need PostgreSQL
```

`CFA_LLM=off` replays the cached model answers and treats a cache miss as an error. CI runs that way.

## Limits

- **Python, not Java.** Moss's backend is Java and Spring Boot. This ledger is Python, because the environment it
  was built in could not reach Maven Central. The design carries over unchanged:
  - Postgres with row-level security, constraints and triggers;
  - an outbox to Kafka;
  - a JWT with an `act` claim;
  - Terraform for GCP.
- **Synthetic data.** It was built to be hard in documented ways, but it is not a customer ledger.
- **Studied test month.** The test month's numbers come from after its first run was studied (first run: accrual
  recall 0.625, did not ship). The held-out month was run once and fails one gate. Both are reported as they came
  out.
- **No real-world exposure.** The model calls go through the Claude Code CLI and are cached. No real DATEV import,
  bank or card feed was tested.
