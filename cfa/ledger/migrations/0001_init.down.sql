drop table if exists outbox, audit_log, journal_entries, proposals, bookings, documents, supplier_bank_changes,
  suppliers, accounts, cost_centres, people, tenants cascade;
drop function if exists refuse_change() cascade;
drop function if exists proposal_decided_once() cascade;
