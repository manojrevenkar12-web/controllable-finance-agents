import type { Document, JournalEntry, Person, Proposal, Quality, Reference, Session } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let token: string | null = null;

export function setToken(t: string | null): void {
  token = t;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = [body.title, body.detail].filter(Boolean).join(": ") || detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("json") ? res.json() : res.text()) as Promise<T>;
}

export type Decision = {
  decision: "approve" | "reject" | "override";
  note?: string;
  payload?: Record<string, unknown>;
};

export const api = {
  devPeople: (tenant: string) => request<Person[]>(`/api/dev/people?tenant=${encodeURIComponent(tenant)}`),
  signIn: (personId: string) =>
    request<Session>("/api/dev/sign-in", { method: "POST", body: JSON.stringify({ person_id: personId }) }),
  reference: () => request<Reference>("/api/reference"),
  people: () => request<Person[]>("/api/people"),
  proposals: (status = "proposed") => request<Proposal[]>(`/api/proposals?status=${status}&limit=2000`),
  documents: (status: string) => request<Document[]>(`/api/documents?status=${status}&limit=1000`),
  decide: (id: string, d: Decision) =>
    request<{ status: string }>(`/api/proposals/${id}/decision`, { method: "POST", body: JSON.stringify(d) }),
  journal: (period: string) => request<JournalEntry[]>(`/api/journal?period=${period}`),
  datev: (period: string) => request<string>(`/api/exports/datev?period=${period}`),
  quality: () => request<Quality>("/api/quality"),
};
