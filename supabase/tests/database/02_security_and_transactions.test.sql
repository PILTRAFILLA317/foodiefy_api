begin;
select plan(22);

create function pg_temp.valid_recipe(p_title text default 'Receta transaccional')
returns jsonb language sql immutable as $$
  select jsonb_build_object(
    'schema_version', '1.0',
    'title', p_title,
    'description', null,
    'source', jsonb_build_object(
      'url', 'https://example.invalid/transaction',
      'canonical_url', null,
      'platform', 'local-test',
      'creator', null,
      'source_kind', 'manual'
    ),
    'ingredients', jsonb_build_array(
      jsonb_build_object(
        'position', 1, 'raw_text', '1.5 kg de prueba', 'name', 'prueba',
        'quantity', 1.5, 'quantity_max', null, 'unit', 'kg',
        'preparation', null, 'group', null, 'evidence_source', 'manual',
        'is_estimated', false
      )
    ),
    'steps', jsonb_build_array(
      jsonb_build_object(
        'position', 1, 'text', 'Probar.', 'duration_seconds', null,
        'temperature_c', null, 'source_timestamp_seconds', null
      )
    ),
    'prep_minutes', null, 'cook_minutes', null, 'total_minutes', null,
    'servings', null, 'yield_text', null, 'nutrition', null,
    'warnings', jsonb_build_array()
  );
$$;

create function pg_temp.invalid_duplicate_ingredients()
returns jsonb language sql immutable as $$
  select jsonb_set(
    pg_temp.valid_recipe('Debe revertirse'),
    '{ingredients}',
    jsonb_build_array(
      pg_temp.valid_recipe() -> 'ingredients' -> 0,
      pg_temp.valid_recipe() -> 'ingredients' -> 0
    )
  );
$$;

create function pg_temp.error_text(p_sql text)
returns text language plpgsql as $$
begin
  execute p_sql;
  return null;
exception when others then
  return sqlstate || ':' || sqlerrm;
end;
$$;

create function pg_temp.affected_rows(p_sql text)
returns bigint language plpgsql as $$
declare
  affected bigint;
begin
  execute p_sql;
  get diagnostics affected = row_count;
  return affected;
end;
$$;

set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-4000-8000-0000000000a1', true);

select lives_ok(
  $$select public.save_recipe_v1(pg_temp.valid_recipe(), '20000000-0000-4000-8000-000000000002', null)$$,
  'owner A saves recipe with children atomically'
);
select is(
  (select count(*)::bigint from public.recipe_ingredients where recipe_id = '20000000-0000-4000-8000-000000000002'),
  1::bigint,
  'decimal ingredient is persisted once'
);
select is(
  (select quantity from public.recipe_ingredients where recipe_id = '20000000-0000-4000-8000-000000000002'),
  1.5::numeric,
  'ingredient quantity remains exact numeric'
);
select is(
  (public.save_recipe_v1(pg_temp.valid_recipe(), '20000000-0000-4000-8000-000000000002', null) ->> 'revision')::bigint,
  1::bigint,
  'creation replay returns the same revision'
);
select is(
  (select count(*)::bigint from public.recipes where id = '20000000-0000-4000-8000-000000000002'),
  1::bigint,
  'creation replay does not duplicate the recipe'
);
select is(
  pg_temp.error_text($$select public.save_recipe_v1(pg_temp.valid_recipe('Cambio'), '20000000-0000-4000-8000-000000000002', 0)$$),
  '40001:recipe_revision_conflict',
  'stale expected revision is visible'
);
select is(
  (public.save_recipe_v1(pg_temp.valid_recipe('Cambio'), '20000000-0000-4000-8000-000000000002', 1) ->> 'revision')::bigint,
  2::bigint,
  'matching expected revision updates once'
);
select is(
  pg_temp.error_text($$select public.save_recipe_v1(pg_temp.invalid_duplicate_ingredients(), '30000000-0000-4000-8000-000000000003', null)$$),
  '23505:duplicate key value violates unique constraint "recipe_ingredients_pkey"',
  'mid-ingredient failure is reported'
);
select is(
  (select count(*)::bigint from public.recipes where id = '30000000-0000-4000-8000-000000000003'),
  0::bigint,
  'mid-ingredient failure leaves no partial recipe'
);
select is(
  pg_temp.error_text($$update public.recipes set revision = 99 where id = '20000000-0000-4000-8000-000000000002'$$),
  '42501:recipe_writes_require_save_recipe_v1',
  'direct REST-equivalent update cannot change revision'
);
select is(
  pg_temp.error_text($$update public.recipes set owner_id = '00000000-0000-4000-8000-0000000000b2' where id = '20000000-0000-4000-8000-000000000002'$$),
  '42501:recipe_writes_require_save_recipe_v1',
  'direct REST-equivalent update cannot change owner'
);
select is(
  pg_temp.error_text($$select public.save_recipe_v1(pg_temp.valid_recipe() || '{"owner_id":"00000000-0000-4000-8000-0000000000b2"}'::jsonb, '50000000-0000-4000-8000-000000000005', null)$$),
  '22023:invalid_recipe_draft_v1',
  'RPC rejects owner_id because draft identity is server-owned'
);

reset role;
insert into storage.objects (bucket_id, name)
values ('recipe-images', '00000000-0000-4000-8000-0000000000a1/original/test.jpg');

set local role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-4000-8000-0000000000b2', true);
select is(
  (select count(*)::bigint from public.recipes where id = '20000000-0000-4000-8000-000000000002'),
  0::bigint,
  'owner B cannot read owner A recipe'
);
select is(
  pg_temp.affected_rows($$update public.recipes set title = 'Intrusión' where id = '20000000-0000-4000-8000-000000000002'$$),
  0::bigint,
  'owner B cannot update owner A recipe'
);
select lives_ok(
  $$insert into public.collections (id, name) values ('40000000-0000-4000-8000-000000000004', 'B')$$,
  'owner B can create a private collection'
);
select is(
  pg_temp.error_text($$insert into public.collection_recipes (collection_id, recipe_id) values ('40000000-0000-4000-8000-000000000004', '20000000-0000-4000-8000-000000000002')$$),
  '23503:insert or update on table "collection_recipes" violates foreign key constraint "collection_recipes_recipe_fkey"',
  'composite key rejects cross-owner collection relation'
);
select is(
  pg_temp.error_text($$insert into public.recipe_ingredients (recipe_id, position, raw_text, name, evidence_source, is_estimated) values ('20000000-0000-4000-8000-000000000002', 2, 'intrusión', 'intrusión', 'manual', false)$$),
  '42501:recipe_writes_require_save_recipe_v1',
  'direct child write is blocked before it can cross owners'
);
select is(
  (select count(*)::bigint from storage.objects where bucket_id = 'recipe-images'),
  0::bigint,
  'owner B cannot read owner A image'
);
select is(
  pg_temp.error_text($$insert into storage.objects (bucket_id, name) values ('recipe-images', '00000000-0000-4000-8000-0000000000a1/original/intrusion.jpg')$$),
  '42501:new row violates row-level security policy for table "objects"',
  'owner B cannot write into owner A image path'
);

select set_config('request.jwt.claim.sub', '00000000-0000-4000-8000-0000000000a1', true);
select is(
  (select count(*)::bigint from storage.objects where bucket_id = 'recipe-images'),
  1::bigint,
  'owner A can read own image'
);
select ok(
  (public.delete_recipe_v1('20000000-0000-4000-8000-000000000002', 2) ->> 'deleted_at') is not null,
  'delete creates an owner-scoped tombstone'
);
select ok(
  (public.save_recipe_v1(pg_temp.valid_recipe(), '20000000-0000-4000-8000-000000000002', null) ->> 'deleted_at') is not null,
  'creation replay cannot resurrect a tombstone'
);

select * from finish();
rollback;
