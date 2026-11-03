import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";
import { api } from "../../shared/api/client";
import type { Document, Proposal, Reference } from "../../shared/api/types";
import { motionTiming } from "../../shared/theme/tokens";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/States";
import { CheckCard, CodingCard } from "./ProposalCard";

type Segment = "ready" | "review" | "checks";

const bucket = (p: Proposal) => (p.evidence?.[0]?.bucket as string | undefined) ?? "review";

export function splitProposals(proposals: Proposal[]) {
  return {
    ready: proposals.filter((p) => p.kind === "coding" && bucket(p) === "ready"),
    review: proposals.filter((p) => p.kind === "coding" && bucket(p) !== "ready"),
    checks: proposals.filter((p) => p.kind === "check"),
  };
}

function BulkApprove({ items }: { items: Proposal[] }) {
  const qc = useQueryClient();
  const [done, setDone] = useState(0);
  const [running, setRunning] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const run = async () => {
    setRunning(true);
    setFailed(null);
    setDone(0);
    for (const p of items) {
      try {
        await api.decide(p.id, { decision: "approve", note: "approved in bulk" });
        setDone((d) => d + 1);
      } catch (e) {
        setFailed((e as Error).message);
        break;
      }
    }
    setRunning(false);
    qc.invalidateQueries({ queryKey: ["proposals"] });
  };
  return (
    <div className="bulk">
      <p style={{ margin: 0 }}>
        <strong>{items.length} bookings</strong> match how this company has booked before, closely enough to
        approve together. Each stays in the audit log with its reason.
      </p>
      <button type="button" className="btn" onClick={run} disabled={running || items.length === 0}>
        {running ? `Approving… ${done} of ${items.length}` : `Approve all ${items.length}`}
      </button>
      {failed && (
        <p role="alert">
          Stopped after {done}: {failed}
        </p>
      )}
    </div>
  );
}

function Inbox({
  proposals,
  documents,
  reference,
}: { proposals: Proposal[]; documents: Document[]; reference: Reference }) {
  const [segment, setSegment] = useState<Segment>("ready");
  const reduce = useReducedMotion();
  const docs = useMemo(() => new Map(documents.map((d) => [d.id, d])), [documents]);
  const parts = splitProposals(proposals);
  const shown = parts[segment];
  const labels: Record<Segment, string> = {
    ready: "Ready to approve",
    review: "Needs a look",
    checks: "Before payment",
  };
  return (
    <>
      <div className="segments" aria-label="Which proposals">
        {(Object.keys(labels) as Segment[]).map((s) => (
          <button key={s} type="button" aria-pressed={s === segment} onClick={() => setSegment(s)}>
            {labels[s]} · {parts[s].length}
          </button>
        ))}
      </div>
      {segment === "ready" && shown.length > 0 && <BulkApprove items={shown} />}
      {shown.length === 0 ? (
        <EmptyState title={`Nothing in “${labels[segment]}”.`}>
          <p>New documents are proposed as they arrive; the other lists may still have work.</p>
        </EmptyState>
      ) : (
        <ul className="list" style={{ listStyle: "none", padding: 0, margin: 0 }}>
          <AnimatePresence initial={false}>
            {shown.slice(0, 40).map((p, i) => (
              <motion.li
                key={p.id}
                layout={!reduce}
                initial={reduce ? false : { opacity: 0, y: 6 }}
                animate={{
                  opacity: 1,
                  y: 0,
                  transition: { ...motionTiming.enter, delay: Math.min(i, 8) * motionTiming.stagger },
                }}
                exit={reduce ? undefined : { opacity: 0, x: 24, transition: motionTiming.exit }}
              >
                {p.kind === "check" ? (
                  <CheckCard p={p} doc={docs.get(p.document_id ?? "")} />
                ) : (
                  <CodingCard p={p} doc={docs.get(p.document_id ?? "")} reference={reference} />
                )}
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
      {shown.length > 40 && <p className="muted">and {shown.length - 40} more.</p>}
    </>
  );
}

export function InboxScreen() {
  const proposals = useQuery({
    queryKey: ["proposals", "proposed"],
    queryFn: () => api.proposals("proposed"),
  });
  const documents = useQuery({
    queryKey: ["documents", "received"],
    queryFn: () => api.documents("received"),
  });
  const reference = useQuery({ queryKey: ["reference"], queryFn: api.reference });
  const pending = proposals.isPending || documents.isPending || reference.isPending;
  const error = proposals.error ?? documents.error ?? reference.error;
  return (
    <>
      <h1>To approve</h1>
      <p className="lede">
        The agents prepare bookings and flag what should not be paid yet. Nothing is booked or held until you
        decide.
      </p>
      {pending ? (
        <Skeleton rows={4} label="Loading proposals" />
      ) : error ? (
        <ErrorState
          what="the proposals"
          error={error}
          retry={() => {
            proposals.refetch();
            documents.refetch();
            reference.refetch();
          }}
        />
      ) : proposals.data && documents.data && reference.data ? (
        proposals.data.filter((p) => p.kind !== "journal").length === 0 ? (
          <EmptyState title="All caught up.">
            <p>Every document has been decided. Month-end entries are under Close.</p>
          </EmptyState>
        ) : (
          <Inbox
            proposals={proposals.data.filter((p) => p.kind !== "journal")}
            documents={documents.data}
            reference={reference.data}
          />
        )
      ) : null}
    </>
  );
}
