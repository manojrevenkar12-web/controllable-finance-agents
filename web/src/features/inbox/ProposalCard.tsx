import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../shared/api/client";
import type { CodingLine, Document, Proposal, Reference } from "../../shared/api/types";
import { eur, issueName } from "../../shared/ui/money";

function Evidence({ confidence }: { confidence: number | null }) {
  const share = Math.max(0, Math.min(1, confidence ?? 0));
  return (
    <span className="evidence">
      <span className="evidence__bar" aria-hidden="true">
        <span className="evidence__fill" style={{ width: `${share * 100}%`, display: "block" }} />
      </span>
      <span>confidence {(share * 100).toFixed(0)} %</span>
    </span>
  );
}

function bucketTag(p: Proposal) {
  const bucket = (p.evidence?.[0]?.bucket as string | undefined) ?? "review";
  return bucket === "ready" ? (
    <span className="tag tag--ok">Ready to approve</span>
  ) : (
    <span className="tag tag--watch">Check before approving</span>
  );
}

export function useDecide() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...d }: { id: string } & Parameters<typeof api.decide>[1]) => api.decide(id, d),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["proposals"] });
      qc.invalidateQueries({ queryKey: ["journal"] });
    },
  });
}

export function CodingCard({ p, doc, reference }: { p: Proposal; doc?: Document; reference: Reference }) {
  const decide = useDecide();
  const [editing, setEditing] = useState(false);
  const lines = (p.payload.lines ?? []) as CodingLine[];
  const [draft, setDraft] = useState<CodingLine[]>(lines);
  const accountName = (n: string) => reference.accounts.find((a) => a.number === n)?.name ?? "";
  const headingId = `p-${p.id}`;
  return (
    <article className="card" aria-labelledby={headingId}>
      <div className="card__head">
        <h3 id={headingId}>
          {doc?.supplier_name ?? p.document_id} <span className="muted">· {doc?.number}</span>
        </h3>
        <span className="amount">{eur(doc?.gross_total)}</span>
      </div>
      <div className="card__head">
        {bucketTag(p)}
        <Evidence confidence={p.confidence} />
      </div>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Line</th>
              <th scope="col" className="num">
                Net
              </th>
              <th scope="col">Account</th>
              <th scope="col">Cost centre</th>
              <th scope="col">Tax key</th>
            </tr>
          </thead>
          <tbody>
            {draft.map((l, i) => (
              <tr key={l.line_no}>
                <td>{doc?.lines[l.line_no]?.description}</td>
                <td className="num">{eur(doc?.lines[l.line_no]?.net)}</td>
                <td>
                  {editing ? (
                    <select
                      aria-label={`Account for line ${i + 1}`}
                      value={l.account}
                      onChange={(e) =>
                        setDraft(draft.map((x, j) => (j === i ? { ...x, account: e.target.value } : x)))
                      }
                    >
                      {reference.accounts.map((a) => (
                        <option key={a.number} value={a.number}>
                          {a.number} {a.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <>
                      {l.account} <span className="muted">{accountName(l.account)}</span>
                    </>
                  )}
                </td>
                <td>
                  {editing ? (
                    <select
                      aria-label={`Cost centre for line ${i + 1}`}
                      value={l.cost_centre}
                      onChange={(e) =>
                        setDraft(draft.map((x, j) => (j === i ? { ...x, cost_centre: e.target.value } : x)))
                      }
                    >
                      {reference.cost_centres.map((c) => (
                        <option key={c.code} value={c.code}>
                          {c.code} {c.department}
                        </option>
                      ))}
                    </select>
                  ) : (
                    l.cost_centre
                  )}
                </td>
                <td>{l.tax_key}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {doc?.notes && <p className="note">Invoice note: {doc.notes}</p>}
      <p className="note">Why: {p.reasoning}</p>
      {decide.isError && (
        <p role="alert" className="tag--hold">
          Not saved: {(decide.error as Error).message}
        </p>
      )}
      <div className="actions">
        {editing ? (
          <>
            <button
              type="button"
              className="btn"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: p.id, decision: "override", payload: { lines: draft } })}
            >
              Save booking
            </button>
            <button
              type="button"
              className="btn btn--quiet"
              onClick={() => {
                setDraft(lines);
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className="btn"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: p.id, decision: "approve" })}
            >
              Approve booking
            </button>
            <button type="button" className="btn btn--quiet" onClick={() => setEditing(true)}>
              Change
            </button>
            <button
              type="button"
              className="btn btn--danger"
              disabled={decide.isPending}
              onClick={() => decide.mutate({ id: p.id, decision: "reject", note: "rejected in the console" })}
            >
              Reject
            </button>
          </>
        )}
      </div>
    </article>
  );
}

export function CheckCard({ p, doc }: { p: Proposal; doc?: Document }) {
  const decide = useDecide();
  const headingId = `p-${p.id}`;
  return (
    <article className="card" aria-labelledby={headingId}>
      <div className="card__head">
        <h3 id={headingId}>
          <span className="tag tag--hold">{issueName(String(p.payload.issue))}</span> {doc?.supplier_name}
          <span className="muted"> · {doc?.number}</span>
        </h3>
        <span className="amount">{eur(doc?.gross_total)}</span>
      </div>
      <p>{p.reasoning}</p>
      {decide.isError && (
        <p role="alert" className="tag--hold">
          Not saved: {(decide.error as Error).message}
        </p>
      )}
      <div className="actions">
        <button
          type="button"
          className="btn btn--danger"
          disabled={decide.isPending}
          onClick={() => decide.mutate({ id: p.id, decision: "approve", note: "payment held" })}
        >
          Hold payment
        </button>
        <button
          type="button"
          className="btn btn--quiet"
          disabled={decide.isPending}
          onClick={() => decide.mutate({ id: p.id, decision: "reject", note: "not an issue" })}
        >
          Dismiss
        </button>
      </div>
    </article>
  );
}
