# Esquema privado de recetas v1

La migración canónica es
`supabase/migrations/20260907152033_create_recipe_contract_v1.sql`. No existe una
segunda carpeta de migraciones en Flutter. El `supabase link` del propietario no
autoriza `db push`, `db reset --linked` ni ninguna otra escritura remota.

## Modelo e invariantes

| Objeto | Responsabilidad |
| --- | --- |
| `recipes` | Copia privada editable por usuario, UUID estable por propietario, revisión optimista, auditoría y tombstone. |
| `recipe_ingredients` | Orden y cantidades `numeric(18,6)` con FK compuesta `(owner_id, recipe_id)`. |
| `recipe_steps` | Orden, duración, temperatura y timestamp opcionales con la misma FK compuesta. |
| `collections` | Colecciones privadas. “Todas” es una vista de UI virtual: no se crea fila ni UUID `0`. |
| `collection_recipes` | Relación con dos FKs compuestas que impiden mezclar colección y receta de propietarios distintos. |
| bucket `recipe-images` | Privado, 10 MiB, JPEG/PNG/WebP, ruta obligatoria `owner_id/...`. |

Todos los cursores empiezan por `owner_id`; las FKs y cascadas tienen índices.
No hay catálogo público, `user_recipes`, caché global ni datos compartidos.

`save_recipe_v1(p_recipe, p_recipe_id, p_expected_revision)` es `SECURITY
INVOKER`. En creación, el UUID enviado por el cliente es también la clave de
reintento: el mismo payload devuelve la fila existente y uno distinto con el
mismo UUID produce `recipe_idempotency_key_reused`. En edición bloquea la fila,
compara la revisión esperada, reemplaza hijos dentro de la misma transacción y
eleva revisión/auditoría mediante trigger. Cualquier fallo revierte receta e
hijos. `delete_recipe_v1` exige revisión y crea un tombstone; un replay de
creación no lo resucita.

Los roles de Data API tienen RLS de propietario con `USING` y `WITH CHECK`.
Escrituras directas de recetas/hijos fallan fuera del contexto RPC; propietario,
revisión y auditoría no son editables por REST. Funciones públicas no necesarias
revocan `EXECUTE` a `PUBLIC`/`anon`. No se usa `user_metadata` ni `service_role`
en cliente.

## Reconstrucción y pruebas locales

Requiere Docker y Supabase CLI. Desde `foodiefy_api/`:

```sh
supabase start
supabase db reset --local
supabase test db --local supabase/tests/database
supabase db advisors --local --type security --level warn --fail-on error
supabase db advisors --local --type performance --level warn --fail-on error
supabase db lint --local --level warning
supabase migration list --local
```

`supabase/seed.sql` solo crea dos identidades y una receta sintéticas en la base
local. No contiene datos personales ni credenciales reutilizables. No uses
`--linked` en estos comandos.

Para la verificación manual del propietario, crea dos cuentas de prueba, guarda
con A una receta que contenga `1.5`, crea una colección de B y comprueba: A ve la
receta/imagen, B no las ve, B no puede asociar el UUID de A, y un PATCH directo
de `owner_id` o `revision` se rechaza. La promoción futura será un `db push`
revisado y autorizado expresamente, mostrando antes el proyecto destino sin
imprimir secretos.

## Rollback seguro

Antes de promoción remota, rollback significa revertir los archivos y reconstruir
otra base local desechable. Si la migración ya se hubiese aplicado y existiesen
datos, no se debe editar la migración ni borrar tablas/bucket: crear una migración
forward que primero revoque RPCs, exporte/verifique datos y solo retire objetos
después de backup y autorización destructiva específica. Los tombstones y objetos
de Storage no se eliminan implícitamente.

## Contratos reservados, no implementados

- Jobs futuros: UUID/idempotencia, propietario, source, estado, etapas,
  intentos, presupuesto/uso y errores observables. No hay cola, worker ni tabla.
- Shopping futuro: ítems privados, procedencia opcional de receta, cantidades
  decimales y unidad original sin asumir conversión. No hay tabla ni realtime.
- Suscripciones/monetización: fuera de fase; no hay tablas, webhooks ni grants.

## Corrección e integración Fase 04

La migración aditiva `20260908101632_phase04_cloud_operations.sql` permite
`source_url` y `platform` desconocidos (`null`) y añade `image_storage_path`
privado por owner/receta. El contrato Pydantic y el snapshot Flutter se han
regenerado. La migración original de Fase 03 permanece intacta.

`cloud_mutation_v1(operation_id, kind, payload)` guarda recibos idempotentes en
`private.cloud_operations`, con RLS y fuera de los esquemas REST expuestos.
Es `SECURITY INVOKER`: owner siempre procede de `auth.uid()`. Sus operaciones:

| kind | payload | Efecto |
| --- | --- | --- |
| `save_recipe` | `id`, `revision` nullable, `draft`, opcional `image_path`, opcional `collection_id` al crear | Llama al RPC v1; receta, hijos, referencia de imagen y asociación inicial en una transacción. |
| `delete_recipe` | `id`, `revision` | Tombstone y retirada de asociaciones atómica. |
| `save_collection` | `id`, `revision` nullable, `name` | Creación/edición privada con revisión. |
| `delete_collection` | `id`, `revision` | Borra colección/relaciones; conserva recetas. |
| `set_collections` | `id` de receta, `collection_ids`, `expected_collection_ids` | Sustituye asociaciones atómicamente y rechaza cambios concurrentes. Las listas esperadas se ordenan por UUID. |

Los recibos verifican igualdad exacta del request. Una clave nueva con revisión
obsoleta produce `40001`; repetir la misma clave/payload recupera el resultado
original, incluso si se perdió la respuesta. Los bloqueos transaccionales
serializan operaciones sobre el mismo owner/objetivo. `library_snapshot_v1()`
lee recetas/hijos, colecciones y rutas privadas en un snapshot MVCC; las rutas
se firman mediante Storage, no se hacen públicas.

La corrección se iteró y probó exclusivamente en el contenedor local
`supabase_db_foodiefy_api`, API 54321/DB 54322. No hubo reset ni promoción remota.
Para rollback operacional: volver a un cliente de solo rescate/lectura,
conservar tablas, recibos, imágenes y backups. No restablecer `NOT NULL` sobre
fuentes desconocidas ni eliminar columnas con datos. Cualquier retirada futura
requiere exportación verificada y una nueva migración forward revisada.

Guía operativa Flutter: `foodiefy/docs/recovery/phase04.md` desde el workspace.
