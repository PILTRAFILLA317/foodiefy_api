-- Synthetic local-only identities. They are not real accounts and carry no private data.
begin;

insert into auth.users (
  instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data, created_at, updated_at
) values
  (
    '00000000-0000-0000-0000-000000000000',
    '00000000-0000-4000-8000-0000000000a1',
    'authenticated', 'authenticated', 'phase03-a@local.foodiefy.invalid', '', now(),
    '{"provider":"email","providers":["email"]}', '{}', now(), now()
  ),
  (
    '00000000-0000-0000-0000-000000000000',
    '00000000-0000-4000-8000-0000000000b2',
    'authenticated', 'authenticated', 'phase03-b@local.foodiefy.invalid', '', now(),
    '{"provider":"email","providers":["email"]}', '{}', now(), now()
  )
on conflict (id) do nothing;

set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-4000-8000-0000000000a1', true);
select public.save_recipe_v1(
  '{
    "schema_version":"1.0",
    "title":"Fixture local sintético",
    "description":null,
    "source":{"url":"https://example.invalid/local-fixture","canonical_url":null,"platform":"local","creator":null,"source_kind":"manual"},
    "ingredients":[{"position":1,"raw_text":"1.25 unidades de prueba","name":"ingrediente de prueba","quantity":1.25,"quantity_max":null,"unit":"unidad","preparation":null,"group":null,"evidence_source":"manual","is_estimated":false}],
    "steps":[{"position":1,"text":"Paso de prueba.","duration_seconds":null,"temperature_c":null,"source_timestamp_seconds":null}],
    "prep_minutes":null,"cook_minutes":null,"total_minutes":null,"servings":null,"yield_text":null,"nutrition":null,"warnings":[]
  }'::jsonb,
  '10000000-0000-4000-8000-000000000001',
  null
);
reset role;

commit;
