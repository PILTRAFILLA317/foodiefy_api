begin;
select plan(4);
select has_table('foodiefy_imports','worker_heartbeats','heartbeat table exists');
select ok((select relrowsecurity from pg_class where oid='foodiefy_imports.worker_heartbeats'::regclass),'RLS enabled');
select ok(not has_table_privilege('authenticated','foodiefy_imports.worker_heartbeats','SELECT'),'app cannot read heartbeat');
select ok(has_table_privilege('foodiefy_import_backend','foodiefy_imports.worker_heartbeats','INSERT'),'backend can heartbeat');
select * from finish();
rollback;
