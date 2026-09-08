begin;
select plan(13);
create function pg_temp.draft() returns jsonb language sql immutable as $$ select '{"schema_version": "1.0", "title": "Ensalada sin cantidades", "description": null, "source": {"url": null, "canonical_url": null, "platform": null, "creator": null, "source_kind": "manual"}, "ingredients": [{"position": 1, "raw_text": "Tomate al gusto", "name": "tomate", "quantity": null, "quantity_max": null, "unit": null, "preparation": null, "group": null, "evidence_source": "source_text", "is_estimated": false}], "steps": [{"position": 1, "text": "Mezclar los ingredientes.", "duration_seconds": null, "temperature_c": null, "source_timestamp_seconds": null}], "prep_minutes": null, "cook_minutes": null, "total_minutes": null, "servings": null, "yield_text": null, "nutrition": null, "warnings": ["La fuente no aporta cantidades, tiempos, raciones ni nutrici\u00f3n."]}'::jsonb; $$;
create function pg_temp.apply(op text, kind text, payload jsonb) returns jsonb language sql as $$
 select public.cloud_mutation_v1(op::uuid,kind,payload);
$$;
set local role authenticated;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-0000000000a1',true);
select lives_ok($$select pg_temp.apply('40000000-0000-4000-8000-000000000001','save_recipe',
 jsonb_build_object('id','40000000-0000-4000-8000-000000000010','revision',null,'draft',pg_temp.draft()))$$,'manual source accepts null');
select is((public.recipe_record_v1('40000000-0000-4000-8000-000000000010')->>'revision')::int,1,'created revision');
select lives_ok($$select pg_temp.apply('40000000-0000-4000-8000-000000000001','save_recipe',
 jsonb_build_object('id','40000000-0000-4000-8000-000000000010','revision',null,'draft',pg_temp.draft()))$$,'same operation replays');
select is((public.recipe_record_v1('40000000-0000-4000-8000-000000000010')->>'revision')::int,1,'replay did not increment');
select throws_ok($$select pg_temp.apply('40000000-0000-4000-8000-000000000001','delete_recipe',
 '{"id":"40000000-0000-4000-8000-000000000010","revision":1}')$$,'23505','operation_id_reused','reused receipt with different payload rejected');
select lives_ok($$select pg_temp.apply('40000000-0000-4000-8000-000000000002','save_recipe',
 jsonb_build_object('id','40000000-0000-4000-8000-000000000010','revision',1,'draft',jsonb_set(pg_temp.draft(),'{title}','"Edited"')))$$,'edit succeeds');
select lives_ok($$select pg_temp.apply('40000000-0000-4000-8000-000000000002','save_recipe',
 jsonb_build_object('id','40000000-0000-4000-8000-000000000010','revision',1,'draft',jsonb_set(pg_temp.draft(),'{title}','"Edited"')))$$,'edit response-loss replay succeeds');
select throws_ok($$select pg_temp.apply('40000000-0000-4000-8000-000000000003','save_recipe',
 jsonb_build_object('id','40000000-0000-4000-8000-000000000010','revision',1,'draft',pg_temp.draft()))$$,'40001','recipe_revision_conflict','stale new operation rejected');
select pg_temp.apply('40000000-0000-4000-8000-000000000004','save_collection','{"id":"40000000-0000-4000-8000-000000000020","name":"Collection","revision":null}');
select pg_temp.apply('40000000-0000-4000-8000-000000000005','set_collections','{"id":"40000000-0000-4000-8000-000000000010","collection_ids":["40000000-0000-4000-8000-000000000020"],"expected_collection_ids":[]}');
select throws_ok($$select pg_temp.apply('40000000-0000-4000-8000-000000000006','set_collections','{"id":"40000000-0000-4000-8000-000000000010","collection_ids":["40000000-0000-4000-8000-000000000099"],"expected_collection_ids":["40000000-0000-4000-8000-000000000020"]}')$$,'23503',null,'invalid move rolls back');
select is((select count(*)::int from public.collection_recipes where recipe_id='40000000-0000-4000-8000-000000000010'),1,'original membership survives failed move');
select throws_ok($$select pg_temp.apply('40000000-0000-4000-8000-000000000007','set_collections','{"id":"40000000-0000-4000-8000-000000000010","collection_ids":[],"expected_collection_ids":[]}')$$,'40001','membership_conflict','concurrent membership update rejected');
select pg_temp.apply('40000000-0000-4000-8000-000000000008','delete_recipe','{"id":"40000000-0000-4000-8000-000000000010","revision":2}');
select is((select count(*)::int from public.collection_recipes where recipe_id='40000000-0000-4000-8000-000000000010'),0,'delete recipe atomically removes memberships');
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-0000000000b2',true);
select is((select count(*)::int from private.cloud_operations),0,'B cannot read A receipts');
reset role;
select * from finish();
rollback;
