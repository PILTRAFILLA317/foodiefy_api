create schema if not exists private;
revoke all on schema private from public, anon;

create table public.recipes (
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  id uuid not null,
  schema_version text not null default '1.0',
  title text not null,
  description text,
  source_url text not null,
  canonical_url text,
  platform text not null,
  creator text,
  source_kind text not null,
  prep_minutes integer,
  cook_minutes integer,
  total_minutes integer,
  servings numeric(18, 6),
  yield_text text,
  nutrition_basis text,
  kcal numeric(18, 6),
  protein_g numeric(18, 6),
  carbs_g numeric(18, 6),
  fat_g numeric(18, 6),
  nutrition_method text,
  nutrition_assumptions text[] not null default '{}',
  nutrition_status text,
  known_mass_g numeric(18, 6),
  warnings text[] not null default '{}',
  revision bigint not null default 1,
  creation_hash text not null,
  created_at timestamptz not null default statement_timestamp(),
  updated_at timestamptz not null default statement_timestamp(),
  deleted_at timestamptz,
  primary key (owner_id, id),
  constraint recipes_schema_version_check check (schema_version = '1.0'),
  constraint recipes_title_check check (btrim(title) <> ''),
  constraint recipes_source_url_check check (source_url ~ '^https?://'),
  constraint recipes_canonical_url_check check (
    canonical_url is null or canonical_url ~ '^https?://'
  ),
  constraint recipes_platform_check check (btrim(platform) <> ''),
  constraint recipes_source_kind_check check (
    source_kind in ('web_page', 'social_post', 'video', 'manual')
  ),
  constraint recipes_prep_minutes_check check (prep_minutes is null or prep_minutes > 0),
  constraint recipes_cook_minutes_check check (cook_minutes is null or cook_minutes > 0),
  constraint recipes_total_minutes_check check (total_minutes is null or total_minutes > 0),
  constraint recipes_servings_check check (
    servings is null or (servings > 0 and servings::text not in ('NaN', 'Infinity', '-Infinity'))
  ),
  constraint recipes_nutrition_values_check check (
    (kcal is null or (kcal >= 0 and kcal::text not in ('NaN', 'Infinity', '-Infinity')))
    and (protein_g is null or (protein_g >= 0 and protein_g::text not in ('NaN', 'Infinity', '-Infinity')))
    and (carbs_g is null or (carbs_g >= 0 and carbs_g::text not in ('NaN', 'Infinity', '-Infinity')))
    and (fat_g is null or (fat_g >= 0 and fat_g::text not in ('NaN', 'Infinity', '-Infinity')))
    and (known_mass_g is null or (known_mass_g > 0 and known_mass_g::text not in ('NaN', 'Infinity', '-Infinity')))
  ),
  constraint recipes_nutrition_shape_check check (
    (
      nutrition_status is null
      and nutrition_basis is null
      and nutrition_method is null
      and kcal is null
      and protein_g is null
      and carbs_g is null
      and fat_g is null
      and known_mass_g is null
      and cardinality(nutrition_assumptions) = 0
    )
    or (
      nutrition_status in ('complete', 'partial', 'unavailable')
      and nutrition_basis in ('whole_recipe', 'per_serving', 'per_100g')
      and nutrition_method in ('source_label', 'calculated', 'ai_estimate', 'manual')
    )
  ),
  constraint recipes_nutrition_unavailable_check check (
    nutrition_status is distinct from 'unavailable'
    or (kcal is null and protein_g is null and carbs_g is null and fat_g is null)
  ),
  constraint recipes_nutrition_complete_check check (
    nutrition_status is distinct from 'complete'
    or (kcal is not null and protein_g is not null and carbs_g is not null and fat_g is not null)
  ),
  constraint recipes_nutrition_assumptions_check check (
    nutrition_method not in ('calculated', 'ai_estimate')
    or (kcal is null and protein_g is null and carbs_g is null and fat_g is null)
    or cardinality(nutrition_assumptions) > 0
  ),
  constraint recipes_per_serving_check check (
    nutrition_basis is distinct from 'per_serving' or servings > 0
  ),
  constraint recipes_per_100g_check check (
    nutrition_basis is distinct from 'per_100g'
    or nutrition_method in ('source_label', 'manual')
    or known_mass_g > 0
  ),
  constraint recipes_revision_check check (revision >= 1),
  constraint recipes_timestamps_check check (updated_at >= created_at)
);

create table public.recipe_ingredients (
  owner_id uuid not null default auth.uid(),
  recipe_id uuid not null,
  position integer not null,
  raw_text text not null,
  name text not null,
  quantity numeric(18, 6),
  quantity_max numeric(18, 6),
  unit text,
  preparation text,
  ingredient_group text,
  evidence_source text not null,
  is_estimated boolean not null,
  primary key (owner_id, recipe_id, position),
  constraint recipe_ingredients_recipe_fkey foreign key (owner_id, recipe_id)
    references public.recipes(owner_id, id) on delete cascade,
  constraint recipe_ingredients_position_check check (position >= 1),
  constraint recipe_ingredients_text_check check (btrim(raw_text) <> '' and btrim(name) <> ''),
  constraint recipe_ingredients_quantity_check check (
    (quantity is null or (quantity > 0 and quantity::text not in ('NaN', 'Infinity', '-Infinity')))
    and (quantity_max is null or (quantity_max > 0 and quantity_max::text not in ('NaN', 'Infinity', '-Infinity')))
    and (quantity is null or quantity_max is null or quantity_max >= quantity)
  ),
  constraint recipe_ingredients_evidence_check check (
    evidence_source in (
      'source_text', 'source_audio', 'source_metadata', 'source_visual', 'manual', 'ai_inference'
    )
  ),
  constraint recipe_ingredients_estimate_check check (
    evidence_source <> 'ai_inference' or is_estimated
  )
);

create table public.recipe_steps (
  owner_id uuid not null default auth.uid(),
  recipe_id uuid not null,
  position integer not null,
  text text not null,
  duration_seconds integer,
  temperature_c numeric(6, 2),
  source_timestamp_seconds numeric(18, 6),
  primary key (owner_id, recipe_id, position),
  constraint recipe_steps_recipe_fkey foreign key (owner_id, recipe_id)
    references public.recipes(owner_id, id) on delete cascade,
  constraint recipe_steps_position_check check (position >= 1),
  constraint recipe_steps_text_check check (btrim(text) <> ''),
  constraint recipe_steps_duration_check check (duration_seconds is null or duration_seconds > 0),
  constraint recipe_steps_temperature_check check (
    temperature_c is null
    or (
      temperature_c between -100 and 500
      and temperature_c::text not in ('NaN', 'Infinity', '-Infinity')
    )
  ),
  constraint recipe_steps_timestamp_check check (
    source_timestamp_seconds is null
    or (
      source_timestamp_seconds >= 0
      and source_timestamp_seconds::text not in ('NaN', 'Infinity', '-Infinity')
    )
  )
);

create table public.collections (
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  id uuid not null default gen_random_uuid(),
  name text not null,
  revision bigint not null default 1,
  created_at timestamptz not null default statement_timestamp(),
  updated_at timestamptz not null default statement_timestamp(),
  primary key (owner_id, id),
  constraint collections_name_check check (btrim(name) <> ''),
  constraint collections_revision_check check (revision >= 1),
  constraint collections_timestamps_check check (updated_at >= created_at)
);

create table public.collection_recipes (
  owner_id uuid not null default auth.uid(),
  collection_id uuid not null,
  recipe_id uuid not null,
  created_at timestamptz not null default statement_timestamp(),
  primary key (owner_id, collection_id, recipe_id),
  constraint collection_recipes_collection_fkey foreign key (owner_id, collection_id)
    references public.collections(owner_id, id) on delete cascade,
  constraint collection_recipes_recipe_fkey foreign key (owner_id, recipe_id)
    references public.recipes(owner_id, id) on delete cascade
);

create index recipes_owner_cursor_idx
  on public.recipes (owner_id, updated_at desc, id);
create index recipes_owner_active_cursor_idx
  on public.recipes (owner_id, updated_at desc, id)
  where deleted_at is null;
create index recipe_ingredients_recipe_idx
  on public.recipe_ingredients (owner_id, recipe_id, position);
create index recipe_steps_recipe_idx
  on public.recipe_steps (owner_id, recipe_id, position);
create index collections_owner_cursor_idx
  on public.collections (owner_id, updated_at desc, id);
create index collection_recipes_recipe_idx
  on public.collection_recipes (owner_id, recipe_id, collection_id);

comment on table public.recipes is
  'Private editable recipe copies. Identity is scoped by owner_id; soft-deleted rows are tombstones.';
comment on table public.collections is
  'User collections. The UI collection Todas is virtual and has no database row.';

create or replace function private.protect_recipe_write_v1()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
  caller_id uuid := (select auth.uid());
begin
  if current_setting('foodiefy.recipe_write_v1', true) is distinct from 'on' then
    raise exception using errcode = '42501', message = 'recipe_writes_require_save_recipe_v1';
  end if;
  if caller_id is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;

  if tg_op = 'INSERT' then
    new.owner_id := caller_id;
    new.revision := 1;
    new.created_at := statement_timestamp();
    new.updated_at := new.created_at;
    new.deleted_at := null;
    return new;
  end if;

  if old.owner_id <> caller_id then
    raise exception using errcode = '42501', message = 'recipe_owner_mismatch';
  end if;

  if tg_op = 'UPDATE' then
    if old.deleted_at is not null then
      raise exception using errcode = 'P0001', message = 'recipe_deleted';
    end if;
    if new.owner_id <> old.owner_id or new.id <> old.id or new.created_at <> old.created_at then
      raise exception using errcode = '42501', message = 'immutable_recipe_system_fields';
    end if;
    new.revision := old.revision + 1;
    new.updated_at := statement_timestamp();
    return new;
  end if;

  return old;
end;
$$;

create or replace function private.protect_recipe_child_write_v1()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
  caller_id uuid := (select auth.uid());
  row_owner uuid := case when tg_op = 'DELETE' then old.owner_id else new.owner_id end;
begin
  if current_setting('foodiefy.recipe_write_v1', true) is distinct from 'on' then
    raise exception using errcode = '42501', message = 'recipe_writes_require_save_recipe_v1';
  end if;
  if caller_id is null or row_owner <> caller_id then
    raise exception using errcode = '42501', message = 'recipe_owner_mismatch';
  end if;
  return case when tg_op = 'DELETE' then old else new end;
end;
$$;

create or replace function private.protect_collection_write_v1()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
  caller_id uuid := (select auth.uid());
begin
  if caller_id is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;
  if tg_op = 'INSERT' then
    new.owner_id := caller_id;
    new.revision := 1;
    new.created_at := statement_timestamp();
    new.updated_at := new.created_at;
    return new;
  end if;
  if old.owner_id <> caller_id then
    raise exception using errcode = '42501', message = 'collection_owner_mismatch';
  end if;
  if tg_op = 'UPDATE' then
    if new.owner_id <> old.owner_id or new.id <> old.id or new.created_at <> old.created_at then
      raise exception using errcode = '42501', message = 'immutable_collection_system_fields';
    end if;
    new.revision := old.revision + 1;
    new.updated_at := statement_timestamp();
    return new;
  end if;
  return old;
end;
$$;

create or replace function private.protect_collection_recipe_write_v1()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
  caller_id uuid := (select auth.uid());
begin
  if caller_id is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;
  if tg_op = 'INSERT' then
    new.owner_id := caller_id;
    new.created_at := statement_timestamp();
    return new;
  end if;
  if old.owner_id <> caller_id then
    raise exception using errcode = '42501', message = 'collection_owner_mismatch';
  end if;
  return old;
end;
$$;

create trigger recipes_protect_write
before insert or update or delete on public.recipes
for each row execute function private.protect_recipe_write_v1();
create trigger recipe_ingredients_protect_write
before insert or update or delete on public.recipe_ingredients
for each row execute function private.protect_recipe_child_write_v1();
create trigger recipe_steps_protect_write
before insert or update or delete on public.recipe_steps
for each row execute function private.protect_recipe_child_write_v1();
create trigger collections_protect_write
before insert or update or delete on public.collections
for each row execute function private.protect_collection_write_v1();
create trigger collection_recipes_protect_write
before insert or update or delete on public.collection_recipes
for each row execute function private.protect_collection_recipe_write_v1();

create or replace function public.recipe_record_v1(p_recipe_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
  select jsonb_build_object(
    'schema_version', r.schema_version,
    'id', r.id,
    'owner_id', r.owner_id,
    'title', r.title,
    'description', r.description,
    'source', jsonb_build_object(
      'url', r.source_url,
      'canonical_url', r.canonical_url,
      'platform', r.platform,
      'creator', r.creator,
      'source_kind', r.source_kind
    ),
    'ingredients', coalesce((
      select jsonb_agg(jsonb_build_object(
        'position', i.position,
        'raw_text', i.raw_text,
        'name', i.name,
        'quantity', i.quantity,
        'quantity_max', i.quantity_max,
        'unit', i.unit,
        'preparation', i.preparation,
        'group', i.ingredient_group,
        'evidence_source', i.evidence_source,
        'is_estimated', i.is_estimated
      ) order by i.position)
      from public.recipe_ingredients i
      where i.owner_id = r.owner_id and i.recipe_id = r.id
    ), '[]'::jsonb),
    'steps', coalesce((
      select jsonb_agg(jsonb_build_object(
        'position', s.position,
        'text', s.text,
        'duration_seconds', s.duration_seconds,
        'temperature_c', s.temperature_c,
        'source_timestamp_seconds', s.source_timestamp_seconds
      ) order by s.position)
      from public.recipe_steps s
      where s.owner_id = r.owner_id and s.recipe_id = r.id
    ), '[]'::jsonb),
    'prep_minutes', r.prep_minutes,
    'cook_minutes', r.cook_minutes,
    'total_minutes', r.total_minutes,
    'servings', r.servings,
    'yield_text', r.yield_text,
    'nutrition', case when r.nutrition_status is null then null else jsonb_build_object(
      'basis', r.nutrition_basis,
      'kcal', r.kcal,
      'protein_g', r.protein_g,
      'carbs_g', r.carbs_g,
      'fat_g', r.fat_g,
      'method', r.nutrition_method,
      'assumptions', to_jsonb(r.nutrition_assumptions),
      'status', r.nutrition_status,
      'known_mass_g', r.known_mass_g
    ) end,
    'warnings', to_jsonb(r.warnings),
    'revision', r.revision,
    'created_at', r.created_at,
    'updated_at', r.updated_at,
    'deleted_at', r.deleted_at
  )
  from public.recipes r
  where r.owner_id = (select auth.uid()) and r.id = p_recipe_id;
$$;

create or replace function private.replace_recipe_children_v1(
  p_owner_id uuid,
  p_recipe_id uuid,
  p_recipe jsonb
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
  item jsonb;
begin
  delete from public.recipe_ingredients
  where owner_id = p_owner_id and recipe_id = p_recipe_id;
  delete from public.recipe_steps
  where owner_id = p_owner_id and recipe_id = p_recipe_id;

  for item in select value from jsonb_array_elements(p_recipe -> 'ingredients') loop
    insert into public.recipe_ingredients (
      owner_id, recipe_id, position, raw_text, name, quantity, quantity_max,
      unit, preparation, ingredient_group, evidence_source, is_estimated
    ) values (
      p_owner_id,
      p_recipe_id,
      (item ->> 'position')::integer,
      item ->> 'raw_text',
      item ->> 'name',
      (item ->> 'quantity')::numeric,
      (item ->> 'quantity_max')::numeric,
      item ->> 'unit',
      item ->> 'preparation',
      item ->> 'group',
      item ->> 'evidence_source',
      (item ->> 'is_estimated')::boolean
    );
  end loop;

  for item in select value from jsonb_array_elements(p_recipe -> 'steps') loop
    insert into public.recipe_steps (
      owner_id, recipe_id, position, text, duration_seconds, temperature_c,
      source_timestamp_seconds
    ) values (
      p_owner_id,
      p_recipe_id,
      (item ->> 'position')::integer,
      item ->> 'text',
      (item ->> 'duration_seconds')::integer,
      (item ->> 'temperature_c')::numeric,
      (item ->> 'source_timestamp_seconds')::numeric
    );
  end loop;
end;
$$;

create or replace function public.save_recipe_v1(
  p_recipe jsonb,
  p_recipe_id uuid,
  p_expected_revision bigint default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  caller_id uuid := (select auth.uid());
  existing public.recipes%rowtype;
  source jsonb := p_recipe -> 'source';
  nutrition jsonb := p_recipe -> 'nutrition';
  payload_hash text := md5(p_recipe::text);
  recipe_exists boolean;
begin
  if caller_id is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;
  if jsonb_typeof(p_recipe) <> 'object'
    or p_recipe ->> 'schema_version' <> '1.0'
    or nullif(btrim(p_recipe ->> 'title'), '') is null
    or jsonb_typeof(source) <> 'object'
    or jsonb_typeof(p_recipe -> 'ingredients') <> 'array'
    or jsonb_array_length(p_recipe -> 'ingredients') = 0
    or jsonb_typeof(p_recipe -> 'steps') <> 'array'
    or jsonb_array_length(p_recipe -> 'steps') = 0
    or jsonb_typeof(p_recipe -> 'warnings') <> 'array'
  then
    raise exception using errcode = '22023', message = 'invalid_recipe_draft_v1';
  end if;
  if exists (
    select 1 from jsonb_object_keys(p_recipe) as key
    where key <> all (array[
      'schema_version', 'title', 'description', 'source', 'ingredients', 'steps',
      'prep_minutes', 'cook_minutes', 'total_minutes', 'servings', 'yield_text',
      'nutrition', 'warnings'
    ])
  ) or exists (
    select 1 from jsonb_object_keys(source) as key
    where key <> all (array['url', 'canonical_url', 'platform', 'creator', 'source_kind'])
  ) or exists (
    select 1
    from jsonb_array_elements(p_recipe -> 'ingredients') as ingredient,
      lateral jsonb_object_keys(ingredient) as key
    where key <> all (array[
      'position', 'raw_text', 'name', 'quantity', 'quantity_max', 'unit',
      'preparation', 'group', 'evidence_source', 'is_estimated'
    ])
  ) or exists (
    select 1
    from jsonb_array_elements(p_recipe -> 'steps') as step,
      lateral jsonb_object_keys(step) as key
    where key <> all (array[
      'position', 'text', 'duration_seconds', 'temperature_c',
      'source_timestamp_seconds'
    ])
  ) or (
    nutrition is distinct from 'null'::jsonb
    and exists (
      select 1 from jsonb_object_keys(nutrition) as key
      where key <> all (array[
        'basis', 'kcal', 'protein_g', 'carbs_g', 'fat_g', 'method',
        'assumptions', 'status', 'known_mass_g'
      ])
    )
  ) then
    raise exception using errcode = '22023', message = 'invalid_recipe_draft_v1';
  end if;

  select * into existing
  from public.recipes
  where owner_id = caller_id and id = p_recipe_id
  for update;
  recipe_exists := found;

  if recipe_exists and p_expected_revision is null then
    if existing.creation_hash <> payload_hash then
      raise exception using errcode = '23505', message = 'recipe_idempotency_key_reused';
    end if;
    return public.recipe_record_v1(p_recipe_id);
  end if;
  if recipe_exists and existing.deleted_at is not null then
    raise exception using errcode = 'P0001', message = 'recipe_deleted';
  end if;
  if recipe_exists and existing.revision <> p_expected_revision then
    raise exception using errcode = '40001', message = 'recipe_revision_conflict';
  end if;
  if not recipe_exists and p_expected_revision is not null then
    raise exception using errcode = 'P0002', message = 'recipe_not_found';
  end if;

  perform set_config('foodiefy.recipe_write_v1', 'on', true);

  if recipe_exists then
    update public.recipes set
      schema_version = p_recipe ->> 'schema_version',
      title = p_recipe ->> 'title',
      description = p_recipe ->> 'description',
      source_url = source ->> 'url',
      canonical_url = source ->> 'canonical_url',
      platform = source ->> 'platform',
      creator = source ->> 'creator',
      source_kind = source ->> 'source_kind',
      prep_minutes = (p_recipe ->> 'prep_minutes')::integer,
      cook_minutes = (p_recipe ->> 'cook_minutes')::integer,
      total_minutes = (p_recipe ->> 'total_minutes')::integer,
      servings = (p_recipe ->> 'servings')::numeric,
      yield_text = p_recipe ->> 'yield_text',
      nutrition_basis = nutrition ->> 'basis',
      kcal = (nutrition ->> 'kcal')::numeric,
      protein_g = (nutrition ->> 'protein_g')::numeric,
      carbs_g = (nutrition ->> 'carbs_g')::numeric,
      fat_g = (nutrition ->> 'fat_g')::numeric,
      nutrition_method = nutrition ->> 'method',
      nutrition_assumptions = coalesce(array(
        select jsonb_array_elements_text(nutrition -> 'assumptions')
      ), '{}'),
      nutrition_status = nutrition ->> 'status',
      known_mass_g = (nutrition ->> 'known_mass_g')::numeric,
      warnings = array(select jsonb_array_elements_text(p_recipe -> 'warnings'))
    where owner_id = caller_id and id = p_recipe_id;
  else
    insert into public.recipes (
      owner_id, id, schema_version, title, description, source_url, canonical_url,
      platform, creator, source_kind, prep_minutes, cook_minutes, total_minutes,
      servings, yield_text, nutrition_basis, kcal, protein_g, carbs_g, fat_g,
      nutrition_method, nutrition_assumptions, nutrition_status, known_mass_g,
      warnings, creation_hash
    ) values (
      caller_id,
      p_recipe_id,
      p_recipe ->> 'schema_version',
      p_recipe ->> 'title',
      p_recipe ->> 'description',
      source ->> 'url',
      source ->> 'canonical_url',
      source ->> 'platform',
      source ->> 'creator',
      source ->> 'source_kind',
      (p_recipe ->> 'prep_minutes')::integer,
      (p_recipe ->> 'cook_minutes')::integer,
      (p_recipe ->> 'total_minutes')::integer,
      (p_recipe ->> 'servings')::numeric,
      p_recipe ->> 'yield_text',
      nutrition ->> 'basis',
      (nutrition ->> 'kcal')::numeric,
      (nutrition ->> 'protein_g')::numeric,
      (nutrition ->> 'carbs_g')::numeric,
      (nutrition ->> 'fat_g')::numeric,
      nutrition ->> 'method',
      coalesce(array(select jsonb_array_elements_text(nutrition -> 'assumptions')), '{}'),
      nutrition ->> 'status',
      (nutrition ->> 'known_mass_g')::numeric,
      array(select jsonb_array_elements_text(p_recipe -> 'warnings')),
      payload_hash
    );
  end if;

  perform private.replace_recipe_children_v1(caller_id, p_recipe_id, p_recipe);
  perform set_config('foodiefy.recipe_write_v1', 'off', true);
  return public.recipe_record_v1(p_recipe_id);
end;
$$;

create or replace function public.delete_recipe_v1(
  p_recipe_id uuid,
  p_expected_revision bigint
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  caller_id uuid := (select auth.uid());
  existing public.recipes%rowtype;
begin
  if caller_id is null then
    raise exception using errcode = '42501', message = 'authentication_required';
  end if;
  select * into existing
  from public.recipes
  where owner_id = caller_id and id = p_recipe_id
  for update;
  if not found then
    raise exception using errcode = 'P0002', message = 'recipe_not_found';
  end if;
  if existing.deleted_at is not null then
    return public.recipe_record_v1(p_recipe_id);
  end if;
  if existing.revision <> p_expected_revision then
    raise exception using errcode = '40001', message = 'recipe_revision_conflict';
  end if;
  perform set_config('foodiefy.recipe_write_v1', 'on', true);
  update public.recipes set deleted_at = statement_timestamp()
  where owner_id = caller_id and id = p_recipe_id;
  perform set_config('foodiefy.recipe_write_v1', 'off', true);
  return public.recipe_record_v1(p_recipe_id);
end;
$$;

alter table public.recipes enable row level security;
alter table public.recipe_ingredients enable row level security;
alter table public.recipe_steps enable row level security;
alter table public.collections enable row level security;
alter table public.collection_recipes enable row level security;

create policy recipes_select_owner on public.recipes for select to authenticated
using ((select auth.uid()) = owner_id);
create policy recipes_insert_owner on public.recipes for insert to authenticated
with check ((select auth.uid()) = owner_id);
create policy recipes_update_owner on public.recipes for update to authenticated
using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy recipes_delete_owner on public.recipes for delete to authenticated
using ((select auth.uid()) = owner_id);

create policy recipe_ingredients_select_owner on public.recipe_ingredients for select to authenticated
using ((select auth.uid()) = owner_id);
create policy recipe_ingredients_insert_owner on public.recipe_ingredients for insert to authenticated
with check ((select auth.uid()) = owner_id);
create policy recipe_ingredients_update_owner on public.recipe_ingredients for update to authenticated
using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy recipe_ingredients_delete_owner on public.recipe_ingredients for delete to authenticated
using ((select auth.uid()) = owner_id);

create policy recipe_steps_select_owner on public.recipe_steps for select to authenticated
using ((select auth.uid()) = owner_id);
create policy recipe_steps_insert_owner on public.recipe_steps for insert to authenticated
with check ((select auth.uid()) = owner_id);
create policy recipe_steps_update_owner on public.recipe_steps for update to authenticated
using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy recipe_steps_delete_owner on public.recipe_steps for delete to authenticated
using ((select auth.uid()) = owner_id);

create policy collections_select_owner on public.collections for select to authenticated
using ((select auth.uid()) = owner_id);
create policy collections_insert_owner on public.collections for insert to authenticated
with check ((select auth.uid()) = owner_id);
create policy collections_update_owner on public.collections for update to authenticated
using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy collections_delete_owner on public.collections for delete to authenticated
using ((select auth.uid()) = owner_id);

create policy collection_recipes_select_owner on public.collection_recipes for select to authenticated
using ((select auth.uid()) = owner_id);
create policy collection_recipes_insert_owner on public.collection_recipes for insert to authenticated
with check ((select auth.uid()) = owner_id);
create policy collection_recipes_update_owner on public.collection_recipes for update to authenticated
using ((select auth.uid()) = owner_id) with check ((select auth.uid()) = owner_id);
create policy collection_recipes_delete_owner on public.collection_recipes for delete to authenticated
using ((select auth.uid()) = owner_id);

revoke all on public.recipes, public.recipe_ingredients, public.recipe_steps,
  public.collections, public.collection_recipes from public, anon, authenticated;
grant select, insert, update, delete on public.recipes to authenticated;
grant select, insert, update, delete on public.recipe_ingredients to authenticated;
grant select, insert, update, delete on public.recipe_steps to authenticated;
grant select, delete on public.collections to authenticated;
grant insert (id, name), update (name) on public.collections to authenticated;
grant select, delete on public.collection_recipes to authenticated;
grant insert (collection_id, recipe_id) on public.collection_recipes to authenticated;

revoke execute on function public.recipe_record_v1(uuid) from public, anon;
revoke execute on function public.save_recipe_v1(jsonb, uuid, bigint) from public, anon;
revoke execute on function public.delete_recipe_v1(uuid, bigint) from public, anon;
grant execute on function public.recipe_record_v1(uuid) to authenticated;
grant execute on function public.save_recipe_v1(jsonb, uuid, bigint) to authenticated;
grant execute on function public.delete_recipe_v1(uuid, bigint) to authenticated;

grant usage on schema private to authenticated;
grant execute on function private.replace_recipe_children_v1(uuid, uuid, jsonb) to authenticated;
revoke execute on function private.protect_recipe_write_v1() from public, anon, authenticated;
revoke execute on function private.protect_recipe_child_write_v1() from public, anon, authenticated;
revoke execute on function private.protect_collection_write_v1() from public, anon, authenticated;
revoke execute on function private.protect_collection_recipe_write_v1() from public, anon, authenticated;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'recipe-images',
  'recipe-images',
  false,
  10485760,
  array['image/jpeg', 'image/png', 'image/webp']
)
on conflict (id) do update set
  public = excluded.public,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create policy recipe_images_select_owner on storage.objects for select to authenticated
using (
  bucket_id = 'recipe-images'
  and (storage.foldername(name))[1] = (select auth.uid())::text
);
create policy recipe_images_insert_owner on storage.objects for insert to authenticated
with check (
  bucket_id = 'recipe-images'
  and (storage.foldername(name))[1] = (select auth.uid())::text
);
create policy recipe_images_update_owner on storage.objects for update to authenticated
using (
  bucket_id = 'recipe-images'
  and (storage.foldername(name))[1] = (select auth.uid())::text
)
with check (
  bucket_id = 'recipe-images'
  and (storage.foldername(name))[1] = (select auth.uid())::text
);
create policy recipe_images_delete_owner on storage.objects for delete to authenticated
using (
  bucket_id = 'recipe-images'
  and (storage.foldername(name))[1] = (select auth.uid())::text
);
