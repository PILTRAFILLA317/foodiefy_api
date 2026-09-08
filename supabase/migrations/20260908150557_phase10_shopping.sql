-- One personal list. Immutable receipts and snapshots survive recipe deletion.
create table public.shopping_lists (
 id uuid primary key default gen_random_uuid(), owner_id uuid not null unique default auth.uid() references auth.users(id) on delete cascade,
 name text not null default 'Mi compra' check(length(name) between 1 and 200), revision bigint not null default 1,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(), unique(owner_id,id)
);
create table public.shopping_items (
 id uuid primary key, owner_id uuid not null default auth.uid(), list_id uuid not null,
 name text not null check(length(trim(name)) between 1 and 200), raw_text text not null check(length(raw_text) between 1 and 10000),
 quantity numeric, quantity_max numeric, unit text, preparation text, checked boolean not null default false, notes text,
 sources jsonb not null default '[]', revision bigint not null default 1,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(), deleted_at timestamptz,
 foreign key(owner_id,list_id) references public.shopping_lists(owner_id,id) on delete cascade,
 check(quantity is null or (quantity>0 and quantity<1e12)),
 check(quantity_max is null or (quantity is not null and quantity_max>=quantity and quantity_max<1e12)),
 check(length(unit)<=100), check(length(preparation)<=500), check(length(notes)<=10000)
);
create index shopping_items_owner_list on public.shopping_items(owner_id,list_id);
create table private.shopping_operations (
 owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
 operation_id uuid not null, request jsonb not null, result jsonb not null,
 primary key(owner_id,operation_id)
);
alter table public.shopping_lists enable row level security;
alter table public.shopping_items enable row level security;
alter table private.shopping_operations enable row level security;
create policy shopping_lists_owner on public.shopping_lists to authenticated using(owner_id=(select auth.uid())) with check(owner_id=(select auth.uid()));
create policy shopping_items_owner on public.shopping_items to authenticated using(owner_id=(select auth.uid())) with check(owner_id=(select auth.uid()));
create policy shopping_operations_owner on private.shopping_operations to authenticated using(owner_id=(select auth.uid())) with check(owner_id=(select auth.uid()));
revoke all on public.shopping_lists, public.shopping_items, private.shopping_operations from public,anon,authenticated;
grant select,insert,update on public.shopping_lists,public.shopping_items to authenticated;
grant select,insert on private.shopping_operations to authenticated;
create function private.shopping_guard() returns trigger language plpgsql set search_path='' as $$
begin
 if current_setting('foodiefy.shopping_write',true) is distinct from 'on' then
 raise exception using errcode='42501',message='shopping_rpc_required'; end if;
 return new;
end $$;
create trigger shopping_lists_guard before insert or update on public.shopping_lists for each row execute function private.shopping_guard();
create trigger shopping_items_guard before insert or update on public.shopping_items for each row execute function private.shopping_guard();
create trigger shopping_operations_guard before insert on private.shopping_operations for each row execute function private.shopping_guard();
revoke all on function private.shopping_guard() from public,anon,authenticated;
create function public.shopping_snapshot_v1() returns jsonb language sql stable security invoker set search_path='' as $$
 select jsonb_build_object('items',coalesce((select jsonb_agg(to_jsonb(i) order by i.created_at,i.id) from public.shopping_items i where owner_id=auth.uid()),'[]'::jsonb));
$$;
create function public.shopping_mutation_v1(p_operation_id uuid,p_kind text,p_payload jsonb) returns jsonb
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
 if p_payload ?| array['owner_id','created_at','updated_at','deleted_at','sources','list_id'] then raise exception using errcode='22023',message='server_owned_fields'; end if;
 perform set_config('foodiefy.shopping_write','on',true);
 insert into public.shopping_lists(owner_id) values(caller) on conflict(owner_id) do nothing;
 select id into lid from public.shopping_lists where owner_id=caller;
 select * into item from public.shopping_items where owner_id=caller and id=target for update;
 if p_kind='add' then
 if found then raise exception using errcode='23505',message='item_exists'; end if;
 if u='kg' then q:=q*1000; qm:=qm*1000; u:='g'; end if;
 -- Exact full name/preparation only, known scalar quantities and mass only.
 if q is not null and qm is null and u='g' then
 select * into item from public.shopping_items where owner_id=caller and deleted_at is null and not checked
 and lower(name)=lower(n) and preparation is not distinct from p_payload->>'preparation'
 and unit='g' and quantity is not null and quantity_max is null order by created_at,id limit 1 for update;
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
revoke all on function public.shopping_snapshot_v1(),public.shopping_mutation_v1(uuid,text,jsonb) from public,anon;
grant execute on function public.shopping_snapshot_v1(),public.shopping_mutation_v1(uuid,text,jsonb) to authenticated;
