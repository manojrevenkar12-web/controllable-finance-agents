-- The ledger: system of record for companies, people, suppliers, documents, proposals, journal entries.
-- Every tenant table carries tenant_id and is guarded by row-level security on app.tenant_id, so a query that
-- forgets its tenant filter still sees only one company. The runtime role (cfa_app) is not the owner.

create table tenants (
  id text primary key,
  name text not null,
  materiality_cents bigint not null check (materiality_cents >= 0),
  datev_tax_keys jsonb not null default '{"VSt19": "9", "VSt7": "8", "RC19": "94", "NONE": ""}'
);

create table people (
  id text primary key,
  tenant_id text not null references tenants(id),
  name text not null,
  email text not null,
  department text not null,
  role text not null check (role in ('employee', 'approver', 'accountant', 'admin'))
);

create table cost_centres (
  tenant_id text not null references tenants(id),
  department text not null,
  code text not null,
  primary key (tenant_id, department)
);

create table accounts (
  tenant_id text not null references tenants(id),
  number text not null,
  name text not null,
  primary key (tenant_id, number)
);

create table suppliers (
  id text primary key,
  tenant_id text not null references tenants(id),
  name text not null,
  country text not null,
  vat_id text not null,
  iban text not null
);

create table supplier_bank_changes (
  id bigserial primary key,
  tenant_id text not null references tenants(id),
  supplier_id text not null references suppliers(id),
  old_iban text not null,
  new_iban text not null,
  verified_at date not null,
  verified_by text not null
);

create table documents (
  id text primary key,
  tenant_id text not null references tenants(id),
  kind text not null check (kind in ('invoice', 'card')),
  supplier_id text not null references suppliers(id),
  number text not null,
  doc_date date not null,
  due_date date,
  iban text,
  requester_id text not null references people(id),
  net_total bigint not null,
  vat_total bigint not null,
  gross_total bigint not null,
  notes text not null default '',
  lines jsonb not null,
  month text not null,
  status text not null default 'received' check (status in ('received', 'booked', 'on_hold')),
  received_at timestamptz not null default now()
);
create index documents_tenant_month on documents (tenant_id, month);
create index documents_supplier on documents (tenant_id, supplier_id, doc_date);

create table bookings (
  document_id text not null references documents(id),
  line_no int not null,
  tenant_id text not null references tenants(id),
  account text not null,
  cost_centre text not null,
  tax_key text not null check (tax_key in ('VSt19', 'VSt7', 'RC19', 'NONE')),
  booked_by text not null,
  booked_at timestamptz not null default now(),
  primary key (document_id, line_no)
);

create table proposals (
  id uuid primary key default gen_random_uuid(),
  tenant_id text not null references tenants(id),
  kind text not null check (kind in ('coding', 'check', 'journal')),
  document_id text references documents(id),
  payload jsonb not null,
  confidence numeric(5, 4) check (confidence between 0 and 1),
  reasoning text not null default '',
  evidence jsonb not null default '[]',
  status text not null default 'proposed' check (status in ('proposed', 'approved', 'rejected', 'overridden')),
  created_by text not null,
  created_at timestamptz not null default now(),
  decided_by text,
  decided_at timestamptz,
  decision_note text,
  final_payload jsonb,
  check ((status = 'proposed') = (decided_by is null)),
  check (decided_by is null or decided_by <> created_by)       -- four eyes: nobody approves their own proposal
);
create index proposals_tenant_status on proposals (tenant_id, status, kind);

create table journal_entries (
  id bigserial primary key,
  tenant_id text not null references tenants(id),
  period text not null,
  debit text not null,
  credit text not null,
  amount_cents bigint not null check (amount_cents > 0),
  cost_centre text not null,
  text text not null,
  document_id text references documents(id),
  proposal_id uuid not null unique references proposals(id),
  posted_by text not null,
  posted_at timestamptz not null default now(),
  check (debit <> credit)
);

create table audit_log (
  id bigserial primary key,
  tenant_id text not null references tenants(id),
  actor text not null,
  action text not null,
  subject text not null,
  detail jsonb not null default '{}',
  at timestamptz not null default now()
);

create table outbox (
  id bigserial primary key,
  tenant_id text not null references tenants(id),
  topic text not null,
  key text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  published_at timestamptz
);

-- Records that must never change once written.
create function refuse_change() returns trigger language plpgsql as $$
begin
  raise exception '% is append-only', tg_table_name using errcode = 'P0001';
end $$;
create trigger audit_log_append_only before update or delete on audit_log for each row execute function refuse_change();
create trigger journal_append_only before update or delete on journal_entries for each row execute function refuse_change();

-- A decided proposal stays decided.
create function proposal_decided_once() returns trigger language plpgsql as $$
begin
  if old.status <> 'proposed' then
    raise exception 'proposal % is already %', old.id, old.status using errcode = 'P0001';
  end if;
  return new;
end $$;
create trigger proposals_decided_once before update on proposals for each row execute function proposal_decided_once();

-- Tenant isolation, forced for the table owner as well.
do $$
declare t text;
begin
  foreach t in array array['people', 'cost_centres', 'accounts', 'suppliers', 'supplier_bank_changes', 'documents',
                           'bookings', 'proposals', 'journal_entries', 'audit_log', 'outbox'] loop
    execute format('alter table %I enable row level security', t);
    execute format('alter table %I force row level security', t);
    execute format('create policy tenant_isolation on %I using (tenant_id = current_setting(''app.tenant_id'', true)) '
                   'with check (tenant_id = current_setting(''app.tenant_id'', true))', t);
  end loop;
  alter table tenants enable row level security;
  alter table tenants force row level security;
  create policy tenant_isolation on tenants using (id = current_setting('app.tenant_id', true));
end $$;
