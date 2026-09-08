-- Additive correction: unknown manual/legacy source values are null, never fabricated.
alter table public.recipes alter column source_url drop not null;
alter table public.recipes alter column platform drop not null;
alter table public.recipes add column image_storage_path text;
alter table public.recipes add constraint recipes_image_owner_path check (
  image_storage_path is null or image_storage_path like owner_id::text || '/' || id::text || '/%'
);

create table private.cloud_operations (
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  operation_id uuid not null,
  request jsonb not null,
  result jsonb not null,
  primary key (owner_id, operation_id)
);
alter table private.cloud_operations enable row level security;
create policy cloud_operations_owner on private.cloud_operations to authenticated
  using (owner_id = (select auth.uid())) with check (owner_id = (select auth.uid()));
revoke all on private.cloud_operations from public, anon, authenticated;
grant select, insert on private.cloud_operations to authenticated;

-- A single receipt covers every write, including response-loss retries and moves.
create or replace function public.cloud_mutation_v1(p_operation_id uuid, p_kind text, p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  caller uuid := (select auth.uid());
  request jsonb := jsonb_build_object('kind', p_kind, 'payload', p_payload);
  receipt private.cloud_operations%rowtype;
  result jsonb;
  target uuid := (p_payload->>'id')::uuid;
  existing public.collections%rowtype;
  collection_id uuid;
begin
  if caller is null then
    raise exception using errcode='42501', message='authentication_required';
  end if;
  if p_operation_id is null or target is null then
    raise exception using errcode='22023', message='operation_and_target_required';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(caller::text || p_operation_id::text, 0));
  select * into receipt from private.cloud_operations o
    where o.owner_id=caller and o.operation_id=p_operation_id;
  if found then
    if receipt.request <> request then
      raise exception using errcode='23505', message='operation_id_reused';
    end if;
    return receipt.result;
  end if;
  -- Serializes creates and collection changes for the same target too.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(caller::text || target::text, 1));
  case p_kind
    when 'save_recipe' then
      result := public.save_recipe_v1(p_payload->'draft', target, (p_payload->>'revision')::bigint);
      if result->>'deleted_at' is not null then
        raise exception using errcode='P0001', message='recipe_deleted';
      end if;
      if p_payload ? 'image_path' then
        perform set_config('foodiefy.recipe_write_v1','on',true);
        update public.recipes set image_storage_path=p_payload->>'image_path'
          where owner_id=caller and id=target and image_storage_path is distinct from p_payload->>'image_path';
        perform set_config('foodiefy.recipe_write_v1','off',true);
        result := public.recipe_record_v1(target);
      end if;
      if p_payload->>'collection_id' is not null then
        if p_payload->>'revision' is not null then
          raise exception using errcode='22023', message='initial_collection_only_on_create';
        end if;
        insert into public.collection_recipes(collection_id,recipe_id)
          values((p_payload->>'collection_id')::uuid,target);
      end if;
    when 'delete_recipe' then
      result := public.delete_recipe_v1(target, (p_payload->>'revision')::bigint);
      delete from public.collection_recipes where owner_id=caller and recipe_id=target;
    when 'save_collection' then
      select * into existing from public.collections where owner_id=caller and id=target for update;
      if found then
        if existing.revision is distinct from (p_payload->>'revision')::bigint then
          raise exception using errcode='40001', message='collection_revision_conflict';
        end if;
        update public.collections set name=p_payload->>'name' where owner_id=caller and id=target;
      else
        if p_payload->>'revision' is not null then
          raise exception using errcode='P0002', message='collection_not_found';
        end if;
        insert into public.collections(id,name) values(target,p_payload->>'name');
      end if;
      select to_jsonb(c) into result from public.collections c where c.owner_id=caller and c.id=target;
    when 'delete_collection' then
      select * into existing from public.collections where owner_id=caller and id=target for update;
      if found and existing.revision is distinct from (p_payload->>'revision')::bigint then
        raise exception using errcode='40001', message='collection_revision_conflict';
      end if;
      delete from public.collections where owner_id=caller and id=target;
      result := jsonb_build_object('id',target);
    when 'set_collections' then
      perform 1 from public.recipes where owner_id=caller and id=target and deleted_at is null for update;
      if not found then raise exception using errcode='P0002', message='recipe_not_found'; end if;
      if jsonb_typeof(p_payload->'collection_ids') is distinct from 'array' then
        raise exception using errcode='22023', message='collection_ids_required';
      end if;
      -- Protect against overwriting another device's membership edits.
      if coalesce((select jsonb_agg(cr.collection_id::text order by cr.collection_id::text)
          from public.collection_recipes cr where cr.owner_id=caller and cr.recipe_id=target), '[]'::jsonb)
          is distinct from p_payload->'expected_collection_ids' then
        raise exception using errcode='40001', message='membership_conflict';
      end if;
      delete from public.collection_recipes where owner_id=caller and recipe_id=target;
      for collection_id in select distinct value::uuid from jsonb_array_elements_text(p_payload->'collection_ids') loop
        insert into public.collection_recipes(collection_id,recipe_id) values(collection_id,target);
      end loop;
      result := jsonb_build_object('id',target);
    else raise exception using errcode='22023', message='unknown_cloud_operation';
  end case;
  insert into private.cloud_operations(owner_id,operation_id,request,result)
    values(caller,p_operation_id,request,result);
  return result;
end;
$$;
revoke execute on function public.cloud_mutation_v1(uuid,text,jsonb) from public, anon;
grant execute on function public.cloud_mutation_v1(uuid,text,jsonb) to authenticated;

-- One MVCC snapshot includes children, collections and private image references.
create function public.library_snapshot_v1()
returns jsonb language sql stable security invoker set search_path = '' as $$
select jsonb_build_object(
  'owner_id', (select auth.uid()),
  'recipes', coalesce((select jsonb_agg(public.recipe_record_v1(r.id) order by r.created_at,r.id)
    from public.recipes r where r.owner_id=(select auth.uid()) and r.deleted_at is null),'[]'::jsonb),
  'collections', coalesce((select jsonb_agg(to_jsonb(c) || jsonb_build_object('recipe_ids',
    coalesce((select jsonb_agg(cr.recipe_id order by cr.created_at,cr.recipe_id) from public.collection_recipes cr
      join public.recipes r on r.owner_id=cr.owner_id and r.id=cr.recipe_id and r.deleted_at is null
      where cr.owner_id=c.owner_id and cr.collection_id=c.id),'[]'::jsonb)) order by c.created_at,c.id)
    from public.collections c where c.owner_id=(select auth.uid())),'[]'::jsonb),
  'images', coalesce((select jsonb_object_agg(r.id,r.image_storage_path) from public.recipes r
    where r.owner_id=(select auth.uid()) and r.deleted_at is null and r.image_storage_path is not null),'{}'::jsonb)
);
$$;
revoke execute on function public.library_snapshot_v1() from public, anon;
grant execute on function public.library_snapshot_v1() to authenticated;
