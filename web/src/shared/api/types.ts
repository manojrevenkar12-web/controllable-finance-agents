export type Person = { id: string; name: string; department: string; role: string };

export type Line = { description: string; net: number; vat_rate: number; vat: number };

export type Document = {
  id: string;
  kind: "invoice" | "card";
  supplier_id: string;
  supplier_name: string;
  supplier_country: string;
  number: string;
  date: string;
  iban: string | null;
  requester: string;
  lines: Line[];
  net_total: number;
  vat_total: number;
  gross_total: number;
  notes: string;
  month: string;
  status: string;
};

export type CodingLine = { line_no: number; account: string; cost_centre: string; tax_key: string };

export type Proposal = {
  id: string;
  kind: "coding" | "check" | "journal";
  document_id: string | null;
  payload: Record<string, unknown> & { lines?: CodingLine[] };
  confidence: number | null;
  reasoning: string;
  evidence: Record<string, unknown>[];
  status: "proposed" | "approved" | "rejected" | "overridden";
  created_by: string;
  created_at: string;
};

export type Reference = {
  company: string | null;
  materiality_cents: number | null;
  accounts: { number: string; name: string }[];
  cost_centres: { department: string; code: string }[];
  tax_keys: string[];
};

export type JournalEntry = {
  id: number;
  period: string;
  debit: string;
  credit: string;
  amount_cents: number;
  cost_centre: string;
  text: string;
  posted_by: string;
};

export type Session = { token: string; person: Person; tenant: string };

export type GateCheck = {
  metric: string;
  value: number | null;
  limit: { min?: number; max?: number };
  status: string;
};
export type Release = { agent: string; split: string; ship: boolean; failed: string[]; checks: GateCheck[] };
export type Metric = { value: number | null; low: number | null; high: number | null; k: number; n: number };
export type EvalReport = {
  agent: string;
  split: string;
  month: string;
  documents: number;
  coding: Record<string, Metric> & { buckets: Record<string, number> };
  checks: Record<
    string,
    { tp: number; fp: number; fn: number; precision: number | null; recall: number | null }
  >;
  close: Record<
    string,
    { tp: number; fp: number; fn: number; precision: number | null; recall: number | null }
  >;
  operational: { llm_calls: number; cost_usd: number; p95_ms_per_document: number | null };
};
export type Quality = { evals: EvalReport[]; releases: Release[] };
