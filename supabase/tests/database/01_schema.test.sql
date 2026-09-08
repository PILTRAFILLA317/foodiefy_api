begin;
select plan(15);

select has_table('public', 'recipes', 'recipes table exists');
select has_table('public', 'recipe_ingredients', 'recipe ingredients table exists');
select has_table('public', 'recipe_steps', 'recipe steps table exists');
select has_table('public', 'collections', 'collections table exists');
select has_table('public', 'collection_recipes', 'collection recipe relation exists');

select has_function(
  'public', 'save_recipe_v1', array['jsonb', 'uuid', 'bigint'],
  'transactional recipe save function exists'
);
select has_function(
  'public', 'delete_recipe_v1', array['uuid', 'bigint'],
  'versioned recipe delete function exists'
);
select has_function(
  'public', 'recipe_record_v1', array['uuid'],
  'versioned recipe read function exists'
);

select ok((select relrowsecurity from pg_class where oid = 'public.recipes'::regclass), 'recipes has RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.recipe_ingredients'::regclass), 'ingredients have RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.recipe_steps'::regclass), 'steps have RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.collections'::regclass), 'collections have RLS');
select ok((select relrowsecurity from pg_class where oid = 'public.collection_recipes'::regclass), 'relations have RLS');

select is(
  (select count(*)::integer from pg_policies
   where schemaname = 'public'
     and tablename in ('recipes', 'recipe_ingredients', 'recipe_steps', 'collections', 'collection_recipes')),
  20,
  'every public table has SELECT INSERT UPDATE DELETE owner policies'
);
select is(
  (select public from storage.buckets where id = 'recipe-images'),
  false,
  'recipe image bucket is private'
);

select * from finish();
rollback;
