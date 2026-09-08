-- Internal staged imports. No migration edits/deletion of legacy data.
create schema foodiefy_imports;
revoke all on schema foodiefy_imports from public, anon, authenticated;
do $$ begin
  if not exists (select from pg_roles where rolname = 'foodiefy_import_backend') then
    create role foodiefy_import_backend nologin;
  end if;
end $$;
grant usage on schema foodiefy_imports to foodiefy_import_backend, authenticated;

create table foodiefy_imports.controls (
  singleton boolean primary key default true check(singleton),
  enabled boolean not null default true,
  paid_enabled boolean not null default false,
  visual_enabled boolean not null default false,
  worker_concurrency int not null default 1 check(worker_concurrency between 1 and 2),
  active_per_user int not null default 1 check(active_per_user between 1 and 2),
  daily_imports int not null default 10 check(daily_imports between 1 and 100),
  daily_stt int not null default 10 check(daily_stt between 1 and 100),
  daily_visual int not null default 2 check(daily_visual between 0 and 100),
  global_usd numeric(14,8) not null default 5 check(global_usd >= 0),
  user_daily_usd numeric(14,8) not null default 0.5 check(user_daily_usd >= 0),
  job_usd numeric(14,8) not null default 0.1 check(job_usd >= 0),
  lease_seconds int not null default 120 check(lease_seconds between 30 and 600),
  max_attempts int not null default 3 check(max_attempts between 1 and 5),
  artifact_ttl_seconds int not null default 86400 check(artifact_ttl_seconds between 600 and 604800),
  output_bytes int not null default 1048576 check(output_bytes between 1024 and 2097152)
);
insert into foodiefy_imports.controls default values;
create table foodiefy_imports.jobs (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  idempotency_key text not null check(length(idempotency_key) between 8 and 128),
  payload_hash text not null check(length(payload_hash)=64),
  payload jsonb not null check(octet_length(payload::text)<=8192),
  policy_hash text not null,
  status text not null default 'queued' check(status in ('queued','running','succeeded','partial','failed','canceled')),
  stage text check(stage in ('resolving_source','extracting_metadata','extracting_audio','transcribing','extracting_recipe','analyzing_visual_evidence','finalizing')),
  result jsonb,
  error_code text check(error_code in ('provider_down','source_unavailable','duration_limit','quota_exceeded','budget_exhausted','invalid_output','visual_required_unavailable','canceled')),
  attempt int not null default 0 check(attempt>=0),
  fencing_token bigint not null default 0 check(fencing_token>=0),
  worker_id uuid,
  lease_until timestamptz,
  heartbeat_at timestamptz,
  next_attempt_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(owner_id,idempotency_key), unique(id,owner_id),
  check ((status='running') = (worker_id is not null and lease_until is not null)),
  check(result is null or octet_length(result::text)<=2097152)
);
create index import_claim_idx on foodiefy_imports.jobs(next_attempt_at,created_at) where status in ('queued','running');
create index import_owner_idx on foodiefy_imports.jobs(owner_id,created_at desc,id desc);
create table foodiefy_imports.attempts (
  job_id uuid not null references foodiefy_imports.jobs(id) on delete cascade,
  fencing_token bigint not null,
  worker_id uuid not null,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  outcome text,
  primary key(job_id,fencing_token)
);
create table foodiefy_imports.artifacts (
  job_id uuid not null,
  owner_id uuid not null,
  artifact_key text not null,
  version text not null default '1.0',
  content_hash text not null check(length(content_hash)=64),
  data jsonb,
  blob bytea,
  provider text,
  model text,
  expires_at timestamptz not null,
  invalidated_at timestamptz,
  created_at timestamptz not null default now(),
  primary key(job_id,artifact_key),
  foreign key(job_id,owner_id) references foodiefy_imports.jobs(id,owner_id) on delete cascade,
  check((data is null) <> (blob is null)),
  check(data is null or octet_length(data::text)<=16777216),
  check(blob is null or octet_length(blob)<=16777216)
);
create index import_artifact_ttl_idx on foodiefy_imports.artifacts(expires_at);
create table foodiefy_imports.usage_ledger (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null,
  owner_id uuid not null,
  operation text not null check(operation in ('source','stt','text_extraction','visual_fallback')),
  stage_key text not null,
  attempt int not null check(attempt>=1),
  fencing_token bigint not null,
  request_key uuid not null default gen_random_uuid() unique,
  state text not null check(state in ('reserved','succeeded','failed','uncertain')),
  provider text not null,
  model text not null,
  pricing_version text not null,
  reserved_usd numeric(14,8) not null check(reserved_usd>=0),
  estimated_usd numeric(14,8) check(estimated_usd>=0),
  actual_usd numeric(14,8) check(actual_usd>=0),
  usage jsonb,
  transient boolean not null default false,
  created_at timestamptz not null default now(),
  settled_at timestamptz,
  unique(job_id,stage_key,attempt),
  foreign key(job_id,owner_id) references foodiefy_imports.jobs(id,owner_id) on delete cascade
);
create index import_spend_idx on foodiefy_imports.usage_ledger(owner_id,created_at,operation);
create table foodiefy_imports.private_cache (
  owner_id uuid not null references auth.users(id) on delete cascade,
  source_hash text not null,
  policy_hash text not null,
  result jsonb not null check(octet_length(result::text)<=2097152),
  content_hash text not null,
  expires_at timestamptz not null,
  primary key(owner_id,source_hash,policy_hash)
);

-- No public RPCs or client mutation grants. Credentials stay on server.
alter table foodiefy_imports.controls enable row level security;
alter table foodiefy_imports.jobs enable row level security;
alter table foodiefy_imports.attempts enable row level security;
alter table foodiefy_imports.artifacts enable row level security;
alter table foodiefy_imports.usage_ledger enable row level security;
alter table foodiefy_imports.private_cache enable row level security;
create policy control_read on foodiefy_imports.controls for select to foodiefy_import_backend using(true);
create policy backend_jobs on foodiefy_imports.jobs to foodiefy_import_backend using(true) with check(true);
create policy backend_attempts on foodiefy_imports.attempts to foodiefy_import_backend using(true) with check(true);
create policy backend_artifacts on foodiefy_imports.artifacts to foodiefy_import_backend using(true) with check(true);
create policy backend_ledger on foodiefy_imports.usage_ledger to foodiefy_import_backend using(true) with check(true);
create policy backend_cache on foodiefy_imports.private_cache to foodiefy_import_backend using(true) with check(true);
create policy owner_read on foodiefy_imports.jobs for select to authenticated using(owner_id=(select auth.uid()));
grant select on foodiefy_imports.controls to foodiefy_import_backend;
grant select,insert,update,delete on foodiefy_imports.jobs,foodiefy_imports.attempts,foodiefy_imports.artifacts,foodiefy_imports.usage_ledger,foodiefy_imports.private_cache to foodiefy_import_backend;
grant select on foodiefy_imports.jobs to authenticated;
comment on schema foodiefy_imports is 'Private backend queue; excluded from PostgREST exposed schemas. Provision a server login member of foodiefy_import_backend, never client credentials.';
