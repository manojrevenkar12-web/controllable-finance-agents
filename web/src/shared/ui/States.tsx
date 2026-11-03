import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";

const SKELETON_WIDTHS = ["100%", "96%", "98%", "94%", "99%", "95%"];

export function Skeleton({ rows = 4, label }: { rows?: number; label: string }) {
  return (
    <output aria-label={label} aria-busy="true" className="skeleton-group">
      {SKELETON_WIDTHS.slice(0, rows).map((w) => (
        <span key={w} className="skeleton" style={{ width: w }} />
      ))}
    </output>
  );
}

export function ErrorState({ what, error, retry }: { what: string; error: unknown; retry: () => void }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="state state--error" role="alert">
      <p>
        <strong>Could not load {what}.</strong> {message}
      </p>
      <button type="button" onClick={retry}>
        Try again
      </button>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="state">
      <p>
        <strong>{title}</strong>
      </p>
      {children}
    </div>
  );
}

/** Loading skeleton, error with retry, empty state, or the content: the same four states on every screen. */
export function Async<T>({
  q,
  what,
  isEmpty,
  empty,
  children,
}: {
  q: UseQueryResult<T>;
  what: string;
  isEmpty: (d: T) => boolean;
  empty: ReactNode;
  children: (d: T) => ReactNode;
}) {
  if (q.isPending) return <Skeleton label={`Loading ${what}`} />;
  if (q.isError) return <ErrorState what={what} error={q.error} retry={() => q.refetch()} />;
  if (isEmpty(q.data)) return <>{empty}</>;
  return <>{children(q.data)}</>;
}
