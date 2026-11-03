import { useMutation, useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api } from "../../shared/api/client";
import type { Session } from "../../shared/api/types";
import { ErrorState, Skeleton } from "../../shared/ui/States";

const COMPANIES = [
  ["t-nordlicht", "Nordlicht Robotics GmbH"],
  ["t-elbwerk", "Elbwerk Logistik GmbH"],
  ["t-isarbrot", "Isarbrot Bäckereien GmbH"],
  ["t-moselwein", "Moselwein Handel GmbH"],
] as const;

export function SignIn({ onSignedIn }: { onSignedIn: (s: Session) => void }) {
  const [tenant, setTenant] = useState<string>(COMPANIES[0][0]);
  const [person, setPerson] = useState("");
  const people = useQuery({ queryKey: ["dev-people", tenant], queryFn: () => api.devPeople(tenant) });
  const signIn = useMutation({ mutationFn: (id: string) => api.signIn(id), onSuccess: onSignedIn });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const id = person || people.data?.[0]?.id;
    if (id) signIn.mutate(id);
  };
  return (
    <main className="signin">
      <h1>Sign in</h1>
      <p className="lede">
        Development sign-in: choose a company and a person. In production the company's identity provider
        signs you in.
      </p>
      <form onSubmit={submit}>
        <label htmlFor="company">Company</label>
        <select
          id="company"
          value={tenant}
          onChange={(e) => {
            setTenant(e.target.value);
            setPerson("");
          }}
        >
          {COMPANIES.map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <label htmlFor="person">Person</label>
        {people.isPending ? (
          <Skeleton rows={1} label="Loading people" />
        ) : people.isError ? (
          <ErrorState what="the people of this company" error={people.error} retry={() => people.refetch()} />
        ) : (
          <select
            id="person"
            value={person || people.data[0]?.id}
            onChange={(e) => setPerson(e.target.value)}
          >
            {people.data.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} — {p.role}, {p.department}
              </option>
            ))}
          </select>
        )}
        {signIn.isError && <p role="alert">Sign-in failed: {(signIn.error as Error).message}</p>}
        <p style={{ marginTop: "var(--space-5)" }}>
          <button type="submit" className="btn" disabled={signIn.isPending || !people.data?.length}>
            {signIn.isPending ? "Signing in…" : "Sign in"}
          </button>
        </p>
      </form>
    </main>
  );
}
