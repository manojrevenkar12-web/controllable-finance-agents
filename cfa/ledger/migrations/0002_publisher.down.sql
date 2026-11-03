drop index if exists outbox_unpublished;
drop policy if exists outbox_publisher on outbox;
revoke all on outbox from cfa_publisher;
revoke usage on schema public from cfa_publisher;
