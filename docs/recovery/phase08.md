# Fase 08 · Imports duraderos y control de gasto

## Política y ámbito

El benchmark de Fase 07 sigue **pendiente de medición**. Se aplica la política
conservadora de MASTER_PLAN: JSON-LD directo → caption/subtítulos → audio si
falta texto → gpt-transcribe → caption + transcript separados → GPT-5 nano;
Gemini visual solo con razón respaldada y configuración habilitada. No se
eligieron nuevos modelos, no se ejecutó IA pagada ni se implementó Fase 09.

FastAPI encola; el worker separado realiza adquisición y procesamiento. Mismo
repositorio/runtime, sin Redis/Celery ni builds/despliegues. Flutter recibe los
snapshots del contrato de jobs, **sin implementación de polling ni cambios de UI**.
La receta editable y su persistencia de Fase 04 no cambian.

## Contrato HTTP y autenticación

Todas las rutas de imports exigen `Authorization: Bearer <access_token>` de
Supabase. El JWT se verifica con PyJWT 2.13.0: firma ES256/RS256, exp, iat,
issuer configurado, audience `authenticated`, UUID sub y rol authenticated.
`user_metadata` no autoriza nada. Tokens anónimos o service_role son rechazados.
Nunca se usa el issuer/jku/jwk recibido en el JWT para elegir una URL de claves.

JWKS fijo: `${SUPABASE_URL}/auth/v1/.well-known/jwks.json`, HTTPS validado,
sin proxies implícitos/redirects, timeout 5 s y cuerpo ≤64 KiB. Caché local
5 min y refresco ante kid nuevo, con mínimo de 5 s entre intentos. Si el kid
rotado llega dentro de esa ventana, puede requerir reintentar después de 5 s.
La caché de Supabase puede añadir hasta 10 min según documentación oficial;
revocar una cuenta/sesión no invalida inmediatamente un access token ya firmado.
Esta fase verifica JWT, no añade revocación central por sesión en cada request.

HS256 solo se acepta en `APP_ENV=local` con `SUPABASE_JWT_SECRET` configurado
explícitamente. Producción exige claves asimétricas/JWKS; no hay decode sin
verify ni fallback a secretos legacy en producción.

| Acción | Contrato |
| --- | --- |
| `POST /v1/imports` | Body `{"url":"..."}`, `Idempotency-Key` 8–128 caracteres; 202 con `schema_version`, `job_id` |
| `GET /v1/imports/{job_id}` | Estado, stage, fechas, próximo intento si queued, AnalysisResult nullable y error público |
| `GET /v1/imports?limit=20&cursor=...` | Página privada, máximo 100, cursor opaco por fecha/id, `next_cursor` nullable |
| `POST /v1/imports/{job_id}/cancel` | Cancela queued/running; terminal devuelve estado existente |

Mismo usuario + key + payload devuelve el job existente incluso si terminó;
misma key/payload distinto da 409. Otra cuenta obtiene 404 al leer/cancelar un ID.
Payload POST ≤8 KiB, URL ≤4096, esquema estricto; DNS y SSRF se validan en el
worker. El endpoint legacy permanece desactivado; jamás carga Whisper/Torch.

Estados: queued, running, succeeded, partial, failed, canceled. Stage es
independiente y nullable antes del claim: resolving_source, extracting_metadata,
extracting_audio, transcribing, extracting_recipe, analyzing_visual_evidence,
finalizing. Son etapas observadas, **no porcentajes**. Succeeded significa que
la ejecución terminó; `result.analysis_status=no_recipe` es un resultado terminal
válido y no se reintenta. Partial preserva un borrador incompleto revisable.

Errores de ejecución: provider_down, source_unavailable, duration_limit,
quota_exceeded, budget_exhausted, invalid_output, visual_required_unavailable,
canceled. HTTP también distingue unauthorized/auth_unavailable, not_found,
idempotency_conflict, idempotency_key_required, invalid_cursor e invalid_request.
Errores DB se reducen a service_unavailable sin detalles de conexión.

## Postgres, roles y leases

Migraciones nuevas:

- `20260908133007_phase08_durable_imports.sql`: esquema privado
  `foodiefy_imports`, jobs, attempts, artifacts, usage_ledger, private_cache,
  controls, índices/constraints/RLS y rol NOLOGIN `foodiefy_import_backend`.
- `20260908134439_phase08_backend_role_membership.sql`: habilita SET ROLE para
  el administrador postgres. PostgreSQL 16+ concedió ADMIN pero no SET al crear
  el rol; se verificó el permiso exacto antes de esta corrección aditiva.

Ambas aplicadas **solo a Supabase local** con migration up, sin reset, eliminación
de datos previos ni edición de migraciones aplicadas. No hay SECURITY DEFINER
ni RPC pública privilegiada. `foodiefy_imports` no se añade a schemas expuestos
por PostgREST. RLS en las seis tablas. Authenticated solo tiene SELECT privado
sobre sus jobs; no puede modificar estado/owner ni ver artifacts/ledger/cache.
Las FK compuestas job/owner evitan artifacts o consumos asociados a otra cuenta.

La API y el worker conectan con `IMPORT_DATABASE_URL` (solo servidor) y ejecutan
`SET LOCAL ROLE foodiefy_import_backend` en transacciones cortas. El rol no puede
modificar controls ni concederse gasto. Fuera de local, psycopg usa TLS
`verify-full`; el DSN debe indicar un host/certificado verificable. Provisionar
un login dedicado miembro del rol en el entorno objetivo; nunca poner el DSN,
password o service_role en Flutter. No se ha creado una password de producción.

Claim y reserva usan advisory lock transaccional común para serializar el piloto;
el claim bloquea filas con `FOR UPDATE SKIP LOCKED`. No se mantienen conexiones
ni locks durante requests/FFmpeg. Concurrency global 1–2 según controls.
Claim incrementa fencing_token, crea attempt y asigna lease; heartbeat cada
10 s renueva solo si token/worker/estado/lease siguen siendo válidos.

Un lease vencido se reclama con token nuevo. El worker viejo no puede escribir
artifacts, renovar, liquidar consumo ni finalizar. Al recuperar, reservas abiertas
quedan uncertain. El source fetch gratuito puede repetirse; una llamada pagada
sin respuesta persistida **no se vuelve a enviar automáticamente**. Exactly-once
no se promete para proveedores. La concurrencia se controla en la DB, también
si hay más procesos worker que slots disponibles.

SIGINT/SIGTERM impiden iniciar la siguiente etapa, dejan terminar/persistir una
respuesta en vuelo cuando sea posible y dejan el lease recuperable. Una caída
abrupta no libera mágicamente un gasto enviado. Los temporales locales tienen
cleanup finally/TTL; los artifacts en Postgres expiran y los recolecta el worker.

## Artifacts y retries

Evidencia tipada, audio preparado, frames/vídeo reducido, respuestas pagadas y
transcript se guardan con job/owner, versión, hash, provider/model y expiración.
El piloto guarda artifacts privados en Postgres (JSONB/bytea ≤16 MiB por artifact),
no vídeos permanentes ni buckets públicos. Audio MP3 compacto y visual ≤12 MB;
el original descargado sigue siendo temporal. ZIP interno contiene nombres
propios y se restaura con tamaño y hash acotados. El medio original del usuario
nunca se borra. TTL inicial 24 h; finish/cancel eliminan artifacts. Los restos
de jobs que agotan intentos al recuperar leases se recogen por TTL.

La respuesta de una operación pagada se persiste en la misma transacción que
su ledger antes de devolverla al pipeline. Por ello, una caída incluso antes de
construir el TranscriptResult puede recuperar la respuesta sin pagar otra vez.
En el caso normal, `transcript` se hidrata directamente y el retry del extractor
no vuelve ni a adquirir audio ni a llamar a STT. Text_result/post_result/visual_result
permiten también reutilizar extracciones completadas. Hash corrupto, invalidación
explícita o éxito cuya respuesta ya expiró producen error controlado; **no**
compran silenciosamente otra transcripción. Para repetirla hace falta una nueva
importación deliberada/autorizada, sujeta a las mismas cuotas.

Solo errores transitorios de extracción (red/timeout/408/429/5xx) se reintentan,
con máximo tres intentos y backoff exponencial acotado a 300 s + jitter,
`next_attempt_at`. STT no tiene retry automático de fallo incierto; no_recipe,
URL/auth, límites, rechazo de proveedor y output inválido no se reintentan.
Una caída de DB deja el lease recuperable; nunca se usa un mock de producción.

El caché de borradores es privado por owner + hash del contenido adquirido +
policy/model/prompt/schema/precios/límites. Siempre se resuelve primero la fuente:
una URL idéntica con contenido diferente no reutiliza un borrador viejo. TTL
24 h y hash del resultado; no comparte entre cuentas ni modifica recetas guardadas.
Cambiar política entre enqueue y ejecución falla cerrado en lugar de cobrar con
una política distinta. Vaciar/recrear jobs no es un mecanismo de retry.

## Límites y control de gasto

`foodiefy_imports.controls` es la autoridad compartida entre procesos. Valores
iniciales, **no autorización de gasto**:

| Control | Inicial |
| --- | --- |
| enabled / paid_enabled / visual_enabled | true / **false** / **false** |
| worker_concurrency / active_per_user | 1 / 1; hasta 2 configurable |
| daily_imports / daily_stt / daily_visual por usuario (UTC) | 10 / 10 / 2 |
| global_usd acumulado del ledger / user_daily_usd / job_usd | 5 / 0.50 / 0.10 USD |
| lease_seconds / max_attempts | 120 / 3 |
| artifact_ttl_seconds / output_bytes | 86400 / 1048576 |
| IMPORT_MAX_DURATION_SECONDS / IMPORT_MAX_MEDIA_BYTES | 300 s / 52428800 bytes, configurables hacia abajo |

Cada intento tiene request_key interno UUID. Operaciones source, stt,
text_extraction y visual_fallback se registran separadas. Source no tiene coste
IA (0 explícito); no se pretende medir hosting/red. Cada llamada pagada reserva
antes de enviarse; retries/fallback suman reservas y sus cuotas. Reservas nunca
se devuelven automáticamente, incluso si falló la llamada; su coste puede ser
null. estimated_usd usa usage/precios versionados, actual_usd queda null sin una
factura reconciliada. El control suma el mayor de reserva/estimado/real.

El tope global es acumulado, no se reinicia cada día. No borrar ledger para
recuperar presupuesto; cambios de tope los hace el administrador, deliberadamente.
No hay compra de créditos ni límites de monetización. Reservas conservadoras
controlan este worker según el catálogo, no la factura de gastos ajenos de la cuenta.
Precios desconocidos/catálogo sin reverificar en 30 días bloquean pago. Una
cancelación posterior a la reserva puede dejar una llamada ya en vuelo facturable.

Para habilitar gasto hacen falta **ambos**: controls.paid_enabled administrado y
worker iniciado con `--allow-paid --confirm-paid`, además de keys/config válidas.
Para visual: ENABLE_VISUAL_FALLBACK y controls.visual_enabled; cuota separada.
Ninguno está activado en la entrega. Kill switch general bloquea creación/claim/
siguiente etapa; visual bloquea solo etapas visuales. Cancelar invalida el fencing,
impide siguientes etapas y limpia artifacts, sin prometer refund de requests enviados.

## Operación local exacta sin gasto

Desde `foodiefy_api`, con Supabase local ya iniciado:

```sh
rtk proxy .venv-recovery/bin/python -m pip install -r requirements-dev.lock
rtk proxy supabase migration up --local
rtk proxy .venv-recovery/bin/python -m scripts.run_imports_local api
```

En otra terminal:

```sh
rtk proxy .venv-recovery/bin/python -m scripts.run_imports_local worker
```

El launcher obtiene DB_URL/URL/JWT_SECRET del Supabase local en memoria, comprueba
loopback y no los imprime/escribe. No carga `.env` implícitamente ni permite pago.
La API escucha 127.0.0.1:8000. Se necesitan credenciales/configuración privada del
servidor para otros entornos; liveness funciona sin ellas, readiness devuelve 503.
Readiness comprueba Postgres/control-schema y disponibilidad JWKS/cache (o verificación
local HS256 configurada), **sin IA**. yt-dlp/FFmpeg solo se ejecutan en worker.

Configurar `FOODIEFY_ACCESS_TOKEN` privadamente con un access token de una sesión
Supabase local real del propietario; no copiarlo al chat, logs o argumentos CLI.
Con una URL que se tenga derecho a procesar, el cliente manual evita imprimir
bodies/tokens y muestra solo IDs, estado, stage y errores:

```sh
rtk proxy .venv-recovery/bin/python -m scripts.import_job submit --url '<URL_AUTORIZADA>' --key 'owner-pilot-import-0001'
rtk proxy .venv-recovery/bin/python -m scripts.import_job get --job-id '<JOB_ID_DEVUELTO>'
rtk proxy .venv-recovery/bin/python -m scripts.import_job list
rtk proxy .venv-recovery/bin/python -m scripts.import_job cancel --job-id '<JOB_ID_DEVUELTO>'
```

No se ejecutaron esos comandos con fuentes de terceros. Una web JSON-LD completa
puede terminar sin IA; una ruta pagada se bloqueará con budget_exhausted mientras
no esté autorizada. Si falta un modelo/key, devuelve error controlado, nunca éxito
simulado. Redes sociales siguen bloqueadas en producción/staging por la frontera
de red de Fase 05; macOS local requiere opt-in. No se afirma soporte Linux/Nixpacks.

## Caída/reinicio, aislamiento y presupuesto reproducibles sin pago

Los tests locales usan DB real, firmas JWT, dos usuarios UUID creados solo para
la prueba y proveedores/media explícitamente simulados. Restauran controls y
borran exclusivamente esas cuentas de test al acabar; no tocan cuentas previas.
No arrancar estos tests simultáneamente con un piloto real: modifican temporalmente
los límites locales para probar concurrencia y luego restauran sus valores.

```sh
rtk proxy env FOODIEFY_LOCAL_IMPORT_TESTS=1 .venv-recovery/bin/python -m pytest tests/test_imports.py tests/test_imports_postgres.py -q
rtk proxy env FOODIEFY_LOCAL_IMPORT_TESTS=1 .venv-recovery/bin/python -m pytest tests/test_imports_postgres.py -k 'stt_persisted or paid_response_survives or claim_lease or budget_reservations or cancel_cleans or visual_quota' -q
rtk proxy supabase test db --local supabase/tests/database
rtk proxy supabase db advisors --local --type security --level warn --fail-on error
```

El escenario STT→timeout conserva transcript, programa retry, crea una nueva
instancia Worker y comprueba source=1, media=1, STT=1, extractor=2 en el ledger.
El escenario de lease simula vencimiento, reclama con otro worker/token y prueba
que el anterior no escribe. La respuesta pagada guardada antes de una caída se
recupera sin invocar proveedor; la corrupta/incierta nunca se repaga. Dos reservas
concurrentes que excederían el presupuesto dejan pasar una sola.

Para una caída de proceso manual: iniciar el job con la API, detener el proceso
worker (Ctrl-C para apagado ordenado, SIGKILL sobre **el PID específico del worker**
para caída abrupta), mantener API/Supabase activos y arrancar otra vez el mismo
comando worker. Tras vencer el lease (120 s iniciales), consultar el mismo job_id.
Cerrar/reabrir el cliente no borra el job. No terminar procesos de Supabase ni hacer
reset. Si había una request pagada incierta, el resultado controlado puede ser
provider_down: revisarla es correcto, reenviarla a ciegas no.

El propietario debe verificar otra cuenta → 404/lista vacía, doble POST → mismo ID,
payload diferente → 409, stage sin porcentaje, cancelación sin etapa posterior,
STT=1 en retry, y presupuesto agotado sin nueva request. La app Flutter aún no
consume estas rutas; la prueba física desde la navegación móvil es Fase 09 y
**no se ha ejecutado** aquí.

## Fuentes oficiales y límites de la prueba

- https://supabase.com/changelog.md (cambios relevantes revisados).
- https://supabase.com/docs/guides/auth/jwts
- https://supabase.com/docs/guides/auth/signing-keys
- https://www.psycopg.org/psycopg3/docs/basic/usage.html
- https://pyjwt.readthedocs.io/en/stable/usage.html

Firmas instaladas verificadas: psycopg 3.3.5, PyJWT 2.13.0; dependencias transitivas
fijadas sin upgrades masivos. Capacidades/precios IA siguen los verificados en
Fases 06/07. Pruebas locales no prueban roles/login/TLS de producción, facturación
real, revocación inmediata de JWT, calidad de modelos ni fuentes sociales reales.
No hubo llamadas IA, despliegues, builds, migraciones remotas ni Fase 09.
