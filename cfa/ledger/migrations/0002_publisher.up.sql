-- The outbox publisher relays events of every company to Kafka. It gets its own role, which may read the outbox
-- across companies and mark rows published, and nothing else.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'cfa_publisher') then
    create role cfa_publisher nologin;
  end if;
end $$;
grant usage on schema public to cfa_publisher;
grant select, update (published_at) on outbox to cfa_publisher;
create policy outbox_publisher on outbox to cfa_publisher using (true) with check (true);
create index outbox_unpublished on outbox (id) where published_at is null;
