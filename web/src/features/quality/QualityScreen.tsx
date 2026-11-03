import { useQuery } from "@tanstack/react-query";
import { api } from "../../shared/api/client";
import type { Quality } from "../../shared/api/types";
import { EmptyState, ErrorState, Skeleton } from "../../shared/ui/States";
import { pct } from "../../shared/ui/money";

function fmt(v: number | null) {
  if (v === null) return "–";
  return Number.isInteger(v) ? String(v) : v.toFixed(3);
}

function View({ q }: { q: Quality }) {
  const prod = q.evals.find((e) => e.agent === "production" && e.split === "test");
  return (
    <>
      {prod && (
        <section aria-labelledby="prod-h" style={{ marginBottom: "var(--space-5)" }}>
          <h2 id="prod-h">
            Production agents on {prod.month} ({prod.documents} documents, never used for tuning)
          </h2>
          <div className="grid-2">
            <div className="tile">
              <b>{pct(prod.coding.coverage_ready?.value)}</b>
              of documents ready to approve in bulk
            </div>
            <div className="tile">
              <b>{pct(prod.coding.precision_ready?.value, 1)}</b>
              of those booked exactly right
            </div>
            <div className="tile">
              <b>{pct((prod.checks.all as { recall: number | null }).recall)}</b>
              of payment issues caught, no false alarms on verified bank changes
            </div>
            <div className="tile">
              <b>${prod.operational.cost_usd.toFixed(3)}</b>
              model cost for the month ({prod.operational.llm_calls} calls)
            </div>
          </div>
        </section>
      )}
      <h2>Release decisions</h2>
      <div className="list">
        {q.releases.map((r) => (
          <article key={r.agent} className="card" aria-labelledby={`r-${r.agent}`}>
            <div className="card__head">
              <h3 id={`r-${r.agent}`}>{r.agent}</h3>
              <span className={`tag ${r.ship ? "tag--ok" : "tag--hold"}`}>
                {r.ship ? "Ships" : "Does not ship"}
              </span>
            </div>
            {!r.ship && <p className="muted">Failed: {r.failed.join(", ")}</p>}
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Gate</th>
                    <th scope="col" className="num">
                      Value
                    </th>
                    <th scope="col" className="num">
                      Limit
                    </th>
                    <th scope="col">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {r.checks.map((c) => (
                    <tr key={c.metric}>
                      <th scope="row">{c.metric}</th>
                      <td className="num">{fmt(c.value)}</td>
                      <td className="num">
                        {c.limit.min !== undefined ? `≥ ${c.limit.min}` : `≤ ${c.limit.max}`}
                      </td>
                      <td>{c.status === "pass" ? "passes" : c.status === "fail" ? "fails" : "no cases"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

export function QualityScreen() {
  const q = useQuery({ queryKey: ["quality"], queryFn: api.quality });
  return (
    <>
      <h1>Agent quality</h1>
      <p className="lede">How the agents did on months nobody tuned them on, and which versions may run.</p>
      {q.isPending ? (
        <Skeleton rows={3} label="Loading quality reports" />
      ) : q.isError ? (
        <ErrorState what="the quality reports" error={q.error} retry={() => q.refetch()} />
      ) : q.data.evals.length === 0 && q.data.releases.length === 0 ? (
        <EmptyState title="No evaluation yet.">
          <p>
            Run <code>cfa release</code> to evaluate the agents on the test month.
          </p>
        </EmptyState>
      ) : (
        <View q={q.data} />
      )}
    </>
  );
}
