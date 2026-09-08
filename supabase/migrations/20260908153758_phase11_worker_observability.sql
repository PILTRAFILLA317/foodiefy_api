-- Operational heartbeat, including idle workers; never exposed to app users.
create table foodiefy_imports.worker_heartbeats (
 worker_id uuid primary key,
 seen_at timestamptz not null default now()
);
create index worker_heartbeats_seen on foodiefy_imports.worker_heartbeats(seen_at);
alter table foodiefy_imports.worker_heartbeats enable row level security;
revoke all on foodiefy_imports.worker_heartbeats from public,anon,authenticated;
grant select,insert,update,delete on foodiefy_imports.worker_heartbeats to foodiefy_import_backend;
create policy heartbeat_backend on foodiefy_imports.worker_heartbeats to foodiefy_import_backend using(true) with check(true);
