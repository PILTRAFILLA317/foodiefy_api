# Fase 10 · Compra personal, offline y nutrición

## Comportamiento y límites

Una lista «Mi compra» por cuenta. Desde Home → carrito: añadir producto manual,
editar cantidad/rango/unidad/notas, marcar/desmarcar, contador y sección Comprados.
Vaciar comprados requiere confirmación. Desde receta → Añadir a la compra:
selección, cantidades/rangos/unidades revisables y raciones deseadas. Sin raciones
base se ofrece multiplicador explícito; ×1 conserva originales con aviso.
Las recetas y los ingredientes de `contracts/shopping.v1.fixtures.json` son
sintéticos y revisados para pruebas; no hay fallback de producción ni IA ejecutada.

Factor = deseadas/base solo con ambas positivas. Se admiten decimales, coma decimal
y fracciones como 1/2. Desconocidos permanecen null; un máximo conocido no inventa
mínimo. SQL conserva `numeric` sin redondear a unidades enteras; Dart conserva la
precisión double y solo formatea visualmente a seis decimales (cantidades menores
se muestran en notación científica). No se afirma aritmética decimal arbitraria
exacta en Dart. Cada selección entra completa en una escritura de caché local.

## Normalización

- Solo se suman cantidades escalares conocidas en g/kg: 0,5 kg → 500 g.
- Nombre completo, preparación, forma comercial y estado deben coincidir.
  Se exige además que raw_text, retirando únicamente un prefijo numérico g/kg,
  coincida con el nombre. Si raw conserva un descriptor omitido, no se fusiona.
- g/ml, lata/g, rangos, al gusto, unidades desconocidas, entero/triturado y
  crudo/cocinado quedan separados. No hay densidades ni contenido por envase.
- No se fusiona sobre comprados o tombstones. La separación es deliberada ante
  duda; no hay diccionario semántico, catálogo, precios ni recomendaciones.
- raw_text original permanece en el item y cada aportación en `sources.snapshot`,
  junto con operation_id y origen receta/posición opcionales. El origen no es
  una FK destructiva: borrar o cambiar la receta no cambia la compra generada.

## Contrato y seguridad

API es autoridad: `src/contracts/shopping_v1.py`, schema/manifest/fixtures
`shopping.v1.*`; generador `scripts.generate_shopping_contract` con SHA-256 y copia
reproducible a Flutter. RPC `shopping_mutation_v1(p_operation_id,p_kind,p_payload)`
y `shopping_snapshot_v1()`. UUIDs de operación/item cliente; owner y auditoría
los deriva SQL. Operaciones add/edit/checked/delete. No PATCH directo de items.
Tablas shopping_lists/shopping_items con RLS por auth.uid, FK compuesta owner/lista,
guardas de escritura y recibos privados. SECURITY INVOKER; no service_role móvil.

Los tres archivos de migración Fase 10 son forward-only: la segunda y tercera
refinan validación/normalización y máximos después de aplicar la primera en local.
No se editó ni eliminó una migración aplicada. No reset ni borrado legacy.
Rollback operativo: detener escrituras de compra y conservar tablas, recibos y
cola local. Retirada de datos exigiría otro plan/migración; no eliminar tombstones.

## Offline y conflictos

Drift existente, tabla separada shopping_state con owner_id como clave. Creación
idempotente al abrir la DB, sin generación ni nueva dependencia. La limpieza de
la caché de biblioteca NO limpia esta tabla. Cola máxima 200 operaciones, payload
máximo 32 KB. Persistencia previa al envío; UUID y payload enviados no cambian en
reintentos. Una nueva selección deliberada genera nuevas operaciones. No hay
escrituras al abrir una pantalla. Cada ingrediente tiene su operación independiente;
el lote es atómico en la caché, no una transacción cloud de toda la receta.

Sync al foreground, botón Sincronizar y sondeo de 15 s estando activa; ante fallo
backoff 2/4/8/16/32/64 s. Al recuperar red converge en el siguiente intento; no se
instaló plugin de conectividad. Se muestran pendientes y problemas. Reiniciar
recarga la cola. Las operaciones dependientes aún no enviadas reciben identidad y
revisión devueltas por el servidor (incluye fusión). Una operación enviada no se
reescribe. Sin callbacks toggle remotos: checked es siempre boolean absoluto.

Política por campo:
- checked: gana la operación aceptada en orden por el servidor; nunca reloj móvil.
- nombre/cantidad/rango/unidad/notas y borrar: revisión esperada. Conflicto detiene
  la cola, conserva propuesta y permite consultar servidor y confirmar reaplicación
  con UUID/revisión nuevos. No sobrescribe silenciosamente.
- tombstone: no acepta editar/marcar ni resucita mediante replay de un add antiguo.
- logout: sincronizar, cancelar logout o descartar explícitamente. Una sesión que
  expira o cambia externamente conserva la cola privada de A en disco, no la envía
  con B. Volver a A la recupera. Respuestas tardías llevan guardia de generación.

Descartar pendientes advierte que operaciones ya aceptadas pueden permanecer en
servidor (una respuesta pudo perderse); no es undo. Undo de aportaciones no se
implementa. Los recibos/snapshots permiten diseñarlo sin atribuir cantidades nuevas.
No se extiende la outbox a recetas, importaciones ni otras funciones.

## Nutrición honesta

Detalle muestra receta completa / por ración / por 100 g, metodología, supuestos y
badge Estimación para calculated/ai_estimate. Null muestra —, nunca cero ficticio.
Convertir necesita raciones o masa conocida. Cambiar base es aritmética local,
sin extraer ni llamar a IA. El reparto energético, solo con los tres macros y
energía positiva, usa 4 kcal/g carbohidratos, 4 proteínas y 9 grasas y divide por
su suma. Es aproximado y no obliga a cuadrar con kcal declaradas (fibra/redondeos).

Editor permite entrada manual o etiqueta para receta completa; conservar base
actual mantiene base original, y modificar números les da procedencia manual.
Cambiar ingredientes invalida nutrición anterior; una nueva entrada manual/etiqueta
explícita puede reemplazarla. Los datos de etiqueta no se sobrescriben al abrir.
`VerifiedIngredientNutrition` deja una interfaz futura sin catálogo ni proveedor.

**Recálculo IA no habilitado**: no existe proveedor/cuota nutricional en el backend
actual. La acción explícita informa de indisponibilidad y coste cero; no simula
éxito ni reutiliza la extracción, cuyo contrato prohíbe estimar nutrición. Para
habilitarlo faltan proveedor, cuota/ledger y precio de esta operación; no se afirma
entregada una estimación IA pagada. No son recomendaciones médicas.

## Verificación manual exacta (propietario)

Desde API, exclusivamente local:

```sh
cd /Users/umartin-/Desktop/SprayNPray/FoodiefyWorkspace/foodiefy_api
rtk proxy supabase db push --local
rtk proxy supabase test db --local
rtk proxy .venv-recovery/bin/python -m scripts.test_shopping_local --local
rtk proxy .venv-recovery/bin/python -m scripts.generate_shopping_contract --check --sync-flutter ../foodiefy/contracts
```

Instancia verificada: contenedor supabase_db_foodiefy_api, Auth/PostgREST
127.0.0.1:54321 y PostgreSQL 54322. El smoke crea solo cuentas/datos sintéticos
locales y no imprime credenciales. No usar --linked ni reutilizar esos comandos
contra una URL remota. La configuración pública local existente es
`foodiefy/config/supabase.local.json`; para dispositivo físico ajustar endpoint
alcanzable según phase09.md. La instalación/build nativa la ejecuta el propietario.

Con la app de desarrollo instalada y una cuenta local:

1. Home → carrito → Añadir producto: papel de cocina, sin cantidad; guardar,
   editar notas, marcar y desmarcar. Comprobar contador y confirmación al vaciar.
2. Añadir arroz 500 g y arroz 0,5 kg; sincronizar: un item 1000 g. Añadir arroz
   20 ml y arroz 1 lata: separados. Tomate entero/triturado y pollo crudo/cocinado
   deben conservar nombres/preparación distintos y quedar separados.
3. Abrir una receta revisada de 2 raciones, seleccionar ingredientes y pedir 4:
   cantidades/rangos ×2, al gusto sigue desconocido. Con receta sin raciones usar
   multiplicador explícito 1 o 1/2. Revisar las unidades antes de confirmar.
4. Modo avión: añadir y marcar; cerrar/reabrir proceso. Ver pendientes conservados.
   Reconectar y volver a foreground, esperar siguiente intento o pulsar Sincronizar:
   sin duplicados. Borrar offline, reconectar y comprobar que no reaparece.
5. Dos clientes A: editar cantidad desde ambos. La segunda revisión debe quedar
   pendiente y mostrar propuesta; Revisar conflicto muestra servidor antes de
   confirmar valores locales. Intentar logout con pendientes: probar cancelar,
   sincronizar y descarte explícito por separado. B nunca ve/envía la cola de A.
6. Abrir nutrición: probar conversión por ración, por100g sin masa (no disponible),
   macros desconocidos (—), etiqueta y badge Estimación. Editar ingrediente sin
   introducir nueva nutrición: desaparecen los valores anteriores. Solicitar
   recálculo muestra no habilitado y no inicia IA. No confirmar esto solo por tests.

SDKs reutilizados, sin cambios de versiones/lockfiles: Supabase Flutter 2.10.3,
Drift 2.34.3, uuid 4.5.2. Firmas contrastadas con documentación oficial:
https://supabase.com/docs/reference/dart/rpc y
https://drift.simonbinder.eu/sql_api/custom_queries; changelog Supabase consultado.

Siguiente entrada: verificación nativa de esta fase y decisión explícita sobre el
servicio nutricional pendiente. No avanzar a Fase 11.
