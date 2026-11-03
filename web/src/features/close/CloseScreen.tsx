import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../shared/api/client";
import type { Proposal } from "../../shared/api/types";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/States";
import { eur } from "../../shared/ui/money";
import { useDecide } from "../inbox/ProposalCard";

function EntryCard({ p }: { p: Proposal }) {
  const decide = useDecide();
  const j = p.payload as {
    type: string;
    debit: string;
    credit: string;
    amount_cents: number;
    cost_centre: string;
    text: string;
  };
  const id = `j-${p.id}`;
  return (
    <article className="card" aria-labelledby={id}>
      <div className="card__head">
        <h3 id={id}>
          <span className={`tag ${j.type === "accrual" ? "tag--watch" : ""}`}>
            {j.type === "deferral" ? "Prepaid expense" : j.type === "accrual" ? "Accrual" : "Entry"}
          </span>{" "}
          {j.text}
        </h3>
        <span className="amount">{eur(j.amount_cents)}</span>
      </div>
      <p className="muted">
        Debit {j.debit} · credit {j.credit} · cost centre {j.cost_centre}
      </p>
      <p className="note">{p.reasoning}</p>
      {decide.isError && <p role="alert">Not saved: {(decide.error as Error).message}</p>}
      <div className="actions">
        <button
          type="button"
          className="btn"
          disabled={decide.isPending}
          onClick={() => decide.mutate({ id: p.id, decision: "approve" })}
        >
          Post entry
        </button>
        <button
          type="button"
          className="btn btn--danger"
          disabled={decide.isPending}
          onClick={() => decide.mutate({ id: p.id, decision: "reject", note: "not needed" })}
        >
          Reject
        </button>
      </div>
    </article>
  );
}

function ExportButton({ period }: { period: string }) {
  const [state, setState] = useState<"idle" | "busy" | "error">("idle");
  const download = async () => {
    setState("busy");
    try {
      const csv = await api.datev(period);
      const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
      const a = Object.assign(document.createElement("a"), {
        href: url,
        download: `EXTF_Buchungsstapel_${period}.csv`,
      });
      a.click();
      URL.revokeObjectURL(url);
      setState("idle");
    } catch {
      setState("error");
    }
  };
  return (
    <span>
      <button type="button" className="btn btn--quiet" onClick={download} disabled={state === "busy"}>
        {state === "busy" ? "Preparing export…" : "Download DATEV export"}
      </button>
      {state === "error" && <span role="alert"> The export failed; try again.</span>}
    </span>
  );
}

export function CloseScreen() {
  const proposals = useQuery({
    queryKey: ["proposals", "proposed"],
    queryFn: () => api.proposals("proposed"),
  });
  const entries = (proposals.data ?? []).filter((p) => p.kind === "journal");
  const period = (entries[0]?.payload as { period?: string } | undefined)?.period ?? "";
  const journal = useQuery({
    queryKey: ["journal", period],
    queryFn: () => api.journal(period),
    enabled: !!period,
  });
  return (
    <>
      <h1>Close</h1>
      <p className="lede">
        Month-end entries the close agent proposes: prepaid parts of invoices that cover later months, and
        invoices that are expected but have not arrived. Each shows its arithmetic. Only posted entries reach
        the export.
      </p>
      {proposals.isPending ? (
        <Skeleton rows={3} label="Loading month-end entries" />
      ) : proposals.isError ? (
        <ErrorState what="month-end entries" error={proposals.error} retry={() => proposals.refetch()} />
      ) : entries.length === 0 ? (
        <EmptyState title="No month-end entries to decide.">
          <p>The close agent proposes them when the month is closed.</p>
        </EmptyState>
      ) : (
        <>
          <div className="actions" style={{ marginBottom: "var(--space-4)" }}>
            <ExportButton period={period} />
            <span className="muted">
              {journal.data ? `${journal.data.length} entries posted for ${period}` : ""}
            </span>
          </div>
          <div className="list">
            {entries.map((p) => (
              <EntryCard key={p.id} p={p} />
            ))}
          </div>
        </>
      )}
    </>
  );
}
