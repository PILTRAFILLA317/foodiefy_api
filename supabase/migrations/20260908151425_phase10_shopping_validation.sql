-- Forward-only refinement of the locally applied phase10 migration.
-- Refuse to infer commercial form/state from an incomplete structured name.
create function private.shopping_product_text(raw text) returns text
language sql immutable set search_path='' as $$
 select lower(trim(regexp_replace(trim(raw),'^[0-9]+([.,][0-9]+)?[[:space:]]*(kg|g)[[:space:]]+','','i')));
$$;
revoke all on function private.shopping_product_text(text) from public,anon;
grant execute on function private.shopping_product_text(text) to authenticated;
create or replace function public.shopping_mutation_v1(p_operation_id uuid,p_kind text,p_payload jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare
 caller uuid:=auth.uid(); req jsonb:=jsonb_build_object('kind',p_kind,'payload',p_payload);
 receipt private.shopping_operations%rowtype; item public.shopping_items%rowtype;
 target uuid:=(p_payload->>'id')::uuid; lid uuid; result jsonb;
 q numeric:=(p_payload->>'quantity')::numeric; qm numeric:=(p_payload->>'quantity_max')::numeric;
 u text:=lower(trim(p_payload->>'unit')); n text:=trim(p_payload->>'name');
begin
 if caller is null then raise exception using errcode='42501',message='authentication_required'; end if;
 if p_operation_id is null or target is null or octet_length(p_payload::text)>32000 then raise exception using errcode='22023',message='invalid_operation'; end if;
 -- Serialize all personal mutations, including merges and replay.
 perform pg_advisory_xact_lock(hashtextextended(caller::text,10));
 select * into receipt from private.shopping_operations where owner_id=caller and operation_id=p_operation_id;
 if found then
 if receipt.request<>req then raise exception using errcode='23505',message='operation_id_reused'; end if;
 return receipt.result; end if;
 if jsonb_typeof(p_payload)<>'object' or exists(select 1 from jsonb_object_keys(p_payload) k where k not in ('id','revision','name','raw_text','quantity','quantity_max','unit','preparation','checked','notes','recipe_id','ingredient_position')) then raise exception using errcode='22023',message='server_owned_fields'; end if;
 perform set_config('foodiefy.shopping_write','on',true);
 insert into public.shopping_lists(owner_id) values(caller) on conflict(owner_id) do nothing;
 select id into lid from public.shopping_lists where owner_id=caller;
 select * into item from public.shopping_items where owner_id=caller and id=target for update;
 if p_kind='add' then
 if found then raise exception using errcode='23505',message='item_exists'; end if;
 if u='kg' then q:=q*1000; qm:=qm*1000; u:='g'; end if;
 -- Exact full name/preparation only, known scalar quantities and mass only.
 if q is not null and qm is null and u='g' and private.shopping_product_text(p_payload->>'raw_text')=lower(n) then
 select * into item from public.shopping_items where owner_id=caller and deleted_at is null and not checked
 and lower(name)=lower(n) and preparation is not distinct from p_payload->>'preparation'
 and private.shopping_product_text(raw_text)=lower(name) and unit='g' and quantity is not null and quantity_max is null order by created_at,id limit 1 for update;
 end if;
 if item.id is not null then
 update public.shopping_items set quantity=quantity+q,revision=revision+1,updated_at=now(),
 sources=sources||jsonb_build_array(jsonb_build_object('operation_id',p_operation_id,'snapshot',p_payload)) where id=item.id and owner_id=caller returning to_jsonb(shopping_items) into result;
 else
 insert into public.shopping_items(id,owner_id,list_id,name,raw_text,quantity,quantity_max,unit,preparation,notes,sources)
 values(target,caller,lid,n,p_payload->>'raw_text',q,qm,u,p_payload->>'preparation',p_payload->>'notes',jsonb_build_array(jsonb_build_object('operation_id',p_operation_id,'snapshot',p_payload))) returning to_jsonb(shopping_items) into result;
 end if;
 elsif p_kind in ('edit','checked','delete') then
 if item.id is null or item.deleted_at is not null then raise exception using errcode='P0002',message='item_deleted_or_missing'; end if;
 if p_kind<>'checked' and item.revision is distinct from (p_payload->>'revision')::bigint then raise exception using errcode='40001',message='shopping_revision_conflict'; end if;
 if p_kind='checked' then
 update public.shopping_items set checked=(p_payload->>'checked')::boolean,revision=revision+1,updated_at=now() where id=target and owner_id=caller returning to_jsonb(shopping_items) into result;
 elsif p_kind='delete' then
 update public.shopping_items set deleted_at=now(),revision=revision+1,updated_at=now() where id=target and owner_id=caller returning to_jsonb(shopping_items) into result;
 else
 update public.shopping_items set name=n,quantity=q,quantity_max=qm,unit=u,notes=p_payload->>'notes',revision=revision+1,updated_at=now() where id=target and owner_id=caller returning to_jsonb(shopping_items) into result;
 end if;
 else raise exception using errcode='22023',message='invalid_kind'; end if;
 insert into private.shopping_operations values(caller,p_operation_id,req,result);
 perform set_config('foodiefy.shopping_write','off',true);
 return result;
end $$;
