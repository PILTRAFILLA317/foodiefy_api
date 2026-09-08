# Progreso de recuperación · Foodiefy API

## Fase 09 · 2026-09-08

**Ajustes compatibles para la integración Flutter. No se modifican política de
modelos, límites de gasto, migraciones ni infraestructura.**

### Decisiones y archivos/contratos afectados

- `src/imports/models.py`, `api.py`: description opcional, URL opcional solo si
  existe texto, máximo 6000 bytes UTF-8 y request completo 8192 bytes. El body URL
  antiguo se serializa sin campos null nuevos, conservando su hash/idempotencia.
- `worker.py`: texto pegado como Fragment description independiente, source_type
  pasted_text, procedencia manual y plataforma null. No fetch ni audio/STT/visual.
  Reutiliza cola, auth/ownership, cuotas y ledger de extracción de fase 08.
- `src/acquisition/models.py`, `src/analysis/evidence.py`, `pipeline.py`: ampliación
  aditiva de EvidenceBundle y routing textual. No se concatenan caption/transcript
  ni se convierten textos pegados en instrucciones del sistema.
- `store.py`: cancelación limpia medios pero conserva transcript/respuestas privadas
  hasta TTL; fencing sigue bloqueando resultados tardíos. No se reenvía STT.
- `contracts/imports.v1.*`, `evidence-bundle.v1.*`: regenerados; snapshot imports
  sincronizado al hermano Flutter. RecipeDraft permanece intacto.
- Tests de contrato/DB actualizados para texto autenticado y retención tras cancelar.
  README y guía de fase 08 aclaran el cambio compatible de cancelación.

### Pruebas y resultados reales

| Prueba | Resultado |
| --- | --- |
| `rtk proxy env FOODIEFY_LOCAL_IMPORT_TESTS=1 .venv-recovery/bin/python -m pytest -q` | **PASS: 161 tests**, 220 avisos de deprecación, 18.38 s |
| Suite focalizada imports/auth/Postgres | **PASS: 29 tests**; DB local real, proveedores simulados |
| Texto pegado: dos usuarios, POST idempotente, cuota activa, sin fetch/STT | PASS; ledger source + text_extraction |
| Description separada, límites UTF-8/vacío y plataforma desconocida null | PASS |
| Cancelación conserva transcript, limpia audio y rechaza settlement tardío | PASS |
| Migraciones nuevas/aplicadas, pgTAP/advisors repetidos en Fase 09 | **NO EJECUTADO**; no hay cambios SQL |
| Llamadas pagadas, redes sociales reales, contenido de terceros, despliegues/builds | **NO EJECUTADO** |

### Manual, bloqueos y siguiente entrada

Guía exacta móvil/nativa: `../foodiefy/docs/recovery/phase09.md`. El propietario
puede enviar texto autenticado mediante el mismo POST y comprobar límites sin
adquirir URLs; la extracción real requiere autorización de pago, que sigue ausente.
Android detectado, iPhone no accesible; la prueba física de Compartir y el flujo
real description/STT/visual están pendientes. Se hereda el bloqueo de aislamiento
social/medios en producción. No se avanzó a fase 10.

Commit propuesto, **no ejecutado**: `feat: support pasted evidence in durable imports`.

## Fase 08 · 2026-09-08

**Jobs duraderos implementados y probados con Postgres local. Pago y visual
deshabilitados; sin despliegue ni integración móvil de Fase 09.**

### Decisiones y archivos/contratos afectados

- `src/imports/`: API versionada con JWT Supabase verificado y ownership desde
  sub, idempotencia por usuario/key/payload, consulta/lista/cancelación; worker
  separado con claim atómico, lease, heartbeat, fencing y retries transitorios.
- `store.py`, `session.py`, `worker.py`: evidencia/audio/transcript/respuesta
  pagada persistidos con versión/hash/TTL. Retry de extractor reutiliza STT.
  Respuesta incierta o corrupta falla cerrada, sin repetición automática de pago.
  Ledger separado source/STT/texto/visual, reserva concurrente y caché privada
  por owner/contenido/política. Cancelación impide nuevas etapas y limpia artifacts.
- `supabase/migrations/20260908133007_phase08_durable_imports.sql` y
  `20260908134439_phase08_backend_role_membership.sql`: seis tablas privadas con
  RLS/FK compuestas y rol backend restringido. Aplicadas **solo localmente**, sin
  reset ni editar migraciones aplicadas. La segunda habilita SET ROLE explícito
  requerido por PostgreSQL 16+; no permite al backend modificar controls.
- `src/fastapi_app.py`, `config.py`, `acquisition/resolver.py` y
  `analysis/pipeline.py`: conexión acotada al pipeline existente, callbacks de
  etapas reales y límites de medios. API usa threadpool para DB/auth; adquisición
  queda en worker. Legacy desactivado y readiness sin IA.
- `scripts/generate_import_contract.py`, `contracts/imports.v1.*`: contrato API
  reproducible copiado al hermano Flutter. RecipeDraft sin cambios.
  `scripts/import_job.py` y `run_imports_local.py`: operación manual sin imprimir
  credenciales. `.env.example`, requisitos/lockfiles: configuración de servidor
  y PyJWT 2.13.0/psycopg 3.3.5 fijados, sin upgrades masivos.
- Benchmark aún pendiente: política conservadora de MASTER_PLAN. Defaults:
  1 activo/usuario, concurrency 1 (máximo 2), 5 min/50 MiB, 10 imports y STT/día,
  2 visuales/día, límites 5 USD global acumulado / 0.50 usuario-día / 0.10 job,
  outputs 1 MiB, artifacts 24 h, lease 120 s, máximo 3 intentos. Son topes,
  **no autorización de gasto**; paid_enabled y visual_enabled siguen false.
- [phase08.md](phase08.md) documenta arquitectura, permisos, límites, operación
  exacta y recuperación. Se conservaron los cambios previos de otras fases.

### Pruebas y resultados reales

| Comando/prueba | Resultado |
| --- | --- |
| `rtk proxy env FOODIEFY_LOCAL_IMPORT_TESTS=1 .venv-recovery/bin/python -m pytest -q` | **PASS: 159 tests**, 199 avisos de deprecación, 18.42 s |
| Integración dentro de esa suite | **14 tests con PostgreSQL local real**; adquisición/proveedores simulados explícitamente |
| Dos usuarios/JWT, doble POST/conflicto, cancelación, paginación, RLS/cache | PASS |
| Dos workers/lease/fencing, reservas concurrentes y ledger por etapa | PASS |
| STT OK → extractor falla → nueva instancia Worker | PASS: source=1, media=1, STT=1, extractor=2; transcript reutilizado |
| Respuesta pagada persistida antes de artifact, corrupción e incertidumbre | PASS; no repago automático |
| Visual agotado, kill switches, tamaño output y cleanup | PASS; visual no repaga STT |
| `supabase test db --local supabase/tests/database` | **PASS: 62 pgTAP**, 4 archivos |
| Advisors security local y `supabase db lint --local --level warning` | PASS, sin incidencias |
| Ruff `src tests scripts benchmarks`; `pip check`; instalación dry-run del lock | PASS |
| Generadores imports/analysis/RecipeDraft/evidence `--check` | PASS, snapshots de jobs API/Flutter idénticos |
| API/worker mediante launchers y SIGKILL real; JWT/cuenta de producción | **NO EJECUTADO**; reinicio probado con nueva instancia Worker y lease en DB |
| Flutter test/analyze/build, app física cerrar/reabrir | **NO EJECUTADO**; solo contrato/docs Flutter |
| Fuentes de terceros, llamadas pagadas, benchmark real, builds/despliegues/SQL remoto | **NO EJECUTADO** |

La primera ejecución de integración detectó falta de SET ROLE y falló; la
migración aditiva de membership resolvió el permiso. La suite final indicada
es la ejecución que pasó. Los tests restauraron controls y eliminaron solo
cuentas sintéticas propias; se verificó paid=false, visual=false al terminar.
Sin opt-in local, esos 14 tests se omiten explícitamente; no se presenta esa
omisión como prueba de DB. Los avisos corresponden a FastAPI/Starlette/AnyIO.

### Bloqueos, comprobación manual y siguiente entrada

Seguir [los comandos exactos de Fase 08](phase08.md#operación-local-exacta-sin-gasto):
arrancar API y worker local, suministrar token privadamente, enviar una URL con
permiso y consultar el mismo job tras reiniciar el worker. Comprobar doble POST
con mismo ID, conflicto de payload, otra cuenta sin acceso, etapas sin porcentajes,
cancelación y presupuesto agotado sin nueva llamada. El escenario automatizado
STT→timeout permite comprobar STT=1 sin gasto. El móvil aún no consume jobs.

Se hereda el bloqueo de redes sociales en producción/staging y falta de prueba
de aislamiento de medios Linux/Nixpacks. Verificación local no certifica TLS/roles
de producción, facturas, fidelidad IA ni revocación inmediata de access tokens.
No hay benchmark concluyente ni autorización de pago. Siguiente punto de entrada:
verificación manual de esta fase; integración móvil Fase 09 solo bajo nueva
instrucción. No se continuó a ella.

Commit propuesto, **no ejecutado**:
`feat: add durable staged imports and spend controls`.

## Fase 07 · 2026-09-08

**Infraestructura de benchmark implementada solo en API. Por instrucción expresa
del propietario: 30 slots pendientes, sin fuentes inventadas, sin adquisición
de terceros ni llamadas pagadas. No hay ganador ni cambio de producción.**

### Decisiones y archivos/contratos afectados

- `benchmarks/manifest.v1.json`: **archivo que debe rellenar el propietario**;
  cinco casos por cada una de las seis cohortes de MASTER_PLAN. `url` o
  `local_path`, metadata/medios opcionales, origen, licencia, permiso de
  procesamiento y referencia humana. `contracts.py` y schemas versionados
  validan IDs únicos, rutas por cohorte y hechos esperados con procedencia.
- `benchmarks/runner.py`, `media.py`: dry-run sin proveedores/red/FFmpeg;
  selección de casos/rutas, adquisición reutilizada, inputs B/C/D controlados,
  STT compartido y media local/remota bajo las garantías de Fase 05. Evidencia
  esperada nunca se envía al modelo. Original y salida filtrada separados.
- `benchmarks/ledger.py`: SQLite local exclusivo del benchmark, lock de campaña,
  hashes de inputs/config/código y reserva confirmada antes de request. Una
  reanudación no repaga resultados completados; llamadas inciertas quedan
  bloqueadas con reserva y coste null. Sin retries automáticos ni refunds de
  reservas. No implementa jobs/ledger de producción de Fase 08.
- `benchmarks/gemini.py`, `prices.v1.json`: audio directo y frames/vídeo con
  Gemini Flash-Lite 2.5 económico aún listado oficialmente; precios verificados
  de Nano, Luna y transcripción. Luna usa Responses Structured Outputs y low.
  Se verificaron modalidades/firma y tarifas oficiales; no disponibilidad real
  en la cuenta. Groq G sigue **opcional, no implementado ni medido**.
- `src/analysis/providers.py`: puntos de inyección de catálogo, reasoning y tier estándar para
  reutilizar adaptadores OpenAI existentes; defaults de Fase 06 intactos.
  Sin nuevos paquetes, upgrades ni cambios de lockfiles/RecipeDraft/Flutter/SQL.
- `quality.py`, `reporting.py`: revisión ligada a hash, métricas por hecho y
  procedencia description/transcript/ambos/visual; guardas numéricas/unidades,
  errores graves, corrección humana, p50/p95 y coste por receta útil incluyendo
  fallos. Gasto global deduplicado frente a coste standalone con STT atribuido.
  Comparaciones B/C, C/D, C/E, frames/vídeo y cascadas visuales solicitadas.
- `docs/ai/decision.md`, `reports/20260908T000000Z-dry-run/*`: informes vacíos
  explícitamente pendientes de medición. `.gitignore` excluye fuentes locales e
  informes reales; solo se versiona el dry-run sin contenido fuente. README y
  [guía Fase 07](phase07.md) incluyen comandos y revisión exacta.

### Pruebas y resultados reales

| Comando/prueba | Resultado |
| --- | --- |
| `python -m benchmarks.runner --manifest benchmarks/manifest.v1.json --dry-run --report-dir reports/20260908T000000Z-dry-run --publish-decision` (venv recovery) | **PASS: 30 slots, 0 requests, 0 mediciones**, seis cohortes pendientes |
| `.venv-recovery/bin/python -m pytest tests/test_benchmark.py -q` | **PASS: 24 tests**, 3.84 s |
| `.venv-recovery/bin/python -m pytest -q` | **PASS: 132 tests**, 53 avisos previos de deprecación, 8.35 s |
| `.venv-recovery/bin/ruff check src tests scripts benchmarks` | PASS |
| `benchmarks.schema --check` y generadores analysis/RecipeDraft/evidence `--check` | PASS, sin drift |
| Dry-run sin acceso a runtime, presupuesto agotado, lock, reanudación, caída tras reserva y coste desconocido | PASS automatizado |
| SDK OpenAI real sobre HTTPX simulado: B/C/D, un STT, caption separada, mismo input C/D y Luna low | PASS, **sin llamadas a API real** |
| Gemini audio/frames/vídeo sobre transporte simulado y coste por modalidad | PASS, **sin llamadas a API real** |
| FFmpeg/sandbox macOS reales con vídeo sintético local | PASS: variantes frames/vídeo y limpieza de artifacts |
| Fidelidad: 15→150, g→kg, visual JSON válido sin revisión, hashes de review, p50/p95/coste por útil | PASS automatizado; no mide fidelidad real de modelos |
| `git diff --check`; exclusión Git de `.benchmark-local/` y reports privados | PASS |
| Fuentes de terceros, APIs pagadas, factura real, 3–5 casos revisados por propietario, benchmark real | **NO EJECUTADO**, expresamente aplazado |
| Builds, despliegues, migraciones, Fase 08 | **NO EJECUTADO** |

Durante la ampliación de tests se corrigieron imports de test ausentes detectados
por Ruff/pytest; el resultado final anterior es la ejecución que pasó.

### Bloqueos, manual y siguiente punto de entrada

Faltan las 30 fuentes y referencias, verificación de derechos y autorización
explícita de gasto. Todos los resultados de decisión dicen **pendiente de
medición**. No se han elegido modelos por coste nominal. Se hereda el bloqueo
de redes sociales en producción/staging y de medios fuera del aislamiento
macOS probado; no se demuestra soporte real de plataformas ni Linux/Nixpacks.

El propietario debe rellenar **`benchmarks/manifest.v1.json`**, preparar sus
`reference_path` y ejecutar el dry-run. La [guía](phase07.md#comandos-exactos)
incluye un comando de piloto futuro de tres casos con tope explícito 0.50 USD,
reanudación con el mismo directorio y revisión sin nuevas llamadas mediante
`--report-only`. Ese ejemplo no autoriza ni ha causado gasto.

Comprobar físicamente números/unidades e ingredientes originales, el transcript,
la caption independiente, frames/vídeo y los errores por etapa. Un JSON válido
no basta para útil. Tras revisar el piloto, ampliar solo finalistas; no cambiar
producción ni continuar a Fase 08 sin nueva instrucción.

Commit propuesto, **no ejecutado**:
`test: benchmark text-first recipe extraction pipelines`.

## Fase 06 · 2026-09-08

**Pipeline text-first implementado en API y verificado sin llamadas pagadas.
RecipeDraft v1 y Flutter sin cambios. No se ejecutó el benchmark de Fase 07.**

### Decisiones y archivos/contratos afectados

- `src/analysis/models.py`, `pipeline.py`: interfaces independientes para STT,
  extracción textual y visual; JSON-LD directo → texto existente → audio/STT
  cuando falta evidencia → único fallback visual con motivo respaldado.
  `AttemptState` conserva transcript y liga los reintentos a la fuente.
- `src/analysis/providers.py`: OpenAI SDK 2.26.0, `gpt-transcribe` mediante
  transcriptions y `gpt-5-nano` mediante Responses Structured Outputs; Gemini
  REST opcional para frames/vídeo. Caption completa y transcript separados;
  caption nunca se utiliza como prompt STT. Clientes creados solo tras validar
  configuración y autorización de gasto, sin retries implícitos del SDK.
- `evidence.py`, `visual_validation.py`: procedencia/citas, nulls, conflictos,
  límites de contexto explícitos, metadata controlada por servidor, validación
  de artifacts y eliminación de nutrición no respaldada. Helper que invalida
  nutrición al cambiar ingredientes. Confidence interna aún no calibrada.
- `budget.py`, `pricing.json`: precios versionados/fechados, reserva previa,
  costes desconocidos null, límites por etapa y retry solo transitorio y
  presupuestado. Estado y presupuesto en memoria, de un solo hilo; ledger
  persistente y coordinación entre procesos quedan fuera de esta fase.
- `src/acquisition/social.py`, `media.py`, `worker.py`: selección explícita de
  medio directo, prioridad audio-only y máximo 720p; rechazo de manifiestos.
  FFmpeg produce MP3 o seis frames/MP4 reducido sin audio; validación ffprobe,
  sandbox y limpieza. La adquisición ordinaria sigue sin descargar medios.
- `src/config.py`, `.env.example`, requisitos y lockfiles: configuración backend
  y dependencias fijadas, sin upgrades masivos ni Whisper/Torch. La ruta antigua
  de `src/fastapi_app.py` no puede activar el stack legacy con sus flags previos.
- `scripts/analyze_source.py`: CLI con flags de autorización/presupuesto,
  resultados privados 0600 sin sobrescritura y métricas sin contenido en stdout.
  `scripts/generate_analysis_contract.py`, `contracts/analysis-result.v1.*`:
  schemas local/proveedor y manifest derivados del modelo API.
- `tests/test_analysis.py`, README y [guía Fase 06](phase06.md): contratos,
  operación, fuentes oficiales verificadas y límites. Se conservaron cambios
  previos sin commit/reset. Comparación SHA-256 de **354 archivos Flutter:
  sin cambios**; no se modificó RecipeDraft ni SQL.

### Pruebas y resultados reales

| Comando/prueba | Resultado |
| --- | --- |
| `.venv-recovery/bin/python -m pytest -q` | **PASS: 108 tests**, 53 avisos de deprecación de FastAPI/Starlette/AnyIO, 9.85 s |
| `.venv-recovery/bin/ruff check src tests scripts` | PASS |
| Generadores analysis, evidence y RecipeDraft con `--check` | PASS, snapshots sin drift |
| `pip check`, `pip install --dry-run -r requirements-dev.lock` | PASS |
| `git diff --check` | PASS |
| SDK OpenAI real sobre HTTPX MockTransport y Gemini REST simulado | PASS: payload, separación, schemas, usage, refusal/invalid/incomplete; sin llamadas a proveedores |
| Routing, límites de gasto, retry sin repetir STT, conflictos/nulls y legacy desactivado | PASS automatizado |
| FFmpeg/ffprobe y sandbox macOS con vídeo sintético local | PASS: frames y vídeo reducido, dimensiones/fps/silencio, timestamps y cleanup |
| Modelos/cuenta, aceptación real de schema, fidelidad y costes facturados | **NO EJECUTADO**, requieren llamada autorizada y presupuesto |
| Fuentes sociales reales, benchmark comparativo, builds, despliegues y SQL remoto | **NO EJECUTADO** |

### Bloqueos, manual y siguiente punto de entrada

Redes sociales en producción/staging y medios fuera del sandbox macOS probado
siguen **BLOCKED**. No se acredita soporte real de plataformas ni Linux/Nixpacks.
No se recibieron fuentes del propietario para comprobar las tres rutas reales.
La implementación y sus tests simulados no demuestran calidad de los modelos.

La [guía Fase 06](phase06.md#configuración-y-comandos-manuales) contiene comandos
exactos sin gasto y los tres smokes con flags, presupuesto y confirmación humana.
El propietario debe comprobar caption rica sin STT; vídeo narrado con un STT y
caption/transcript separados; clip visual con fallback justificado o partial,
sin cantidades inventadas. Revisar stages, costes, warnings y citas en el JSON
privado. No se ha ejecutado ninguna llamada real a IA.

Siguiente entrada: esos smokes cuando se autoricen y estén disponibles las
fuentes; aislamiento del host antes de habilitar medios allí. Fase 07 solo con
nueva instrucción, sin declarar ahora un modelo o variante ganadora.

Commit propuesto, **no ejecutado**:
`feat: add text-first recipe extraction with visual fallback`.

## Fase 05 · 2026-09-08

**Capa de adquisición implementada exclusivamente en API, sin IA. Web verificada
con fixtures y transporte HTTPS real; redes sociales sin soporte real acreditado
y bloqueadas en producción. No se continúa a Fase 06.**

### Decisiones y archivos/contratos afectados

- `src/acquisition/models.py`, `resolver.py`, `parsing.py`: `SourceResolver`,
  `EvidenceBundle v1`, estados controlados, procedencias separadas, JSON-LD
  objeto/array/@graph/HowToSection y múltiples recetas sin mezcla. Conserva
  metadata/description, HTML, manuales y automáticos, raw suficiente, idioma,
  hash, tamaños, warnings y tiempos. Contexto limitado con truncamiento explícito;
  no genera prompts ni RecipeDraft ni inventa valores desconocidos.
- `network.py`, `jobs.py`, `worker.py`: HTTP público fijado a sockaddr validado,
  DNS IPv4/IPv6 y redirects revalidados, TLS comprobado, gzip acotado, timeout de
  proceso que cubre DNS/headers/body y parsing, límites CPU/archivos/descriptores,
  entorno mínimo, temporales privados y limpieza `finally`/TTL.
- `social.py`: yt-dlp real 2025.9.26 en proceso macOS con red denegada por el SO,
  RequestHandler exclusivo que pasa por SafeFetcher. Metadata → caption completa
  → subtítulos manuales → automáticos; sin download de medios. El opt-in local
  verifica el sandbox antes de ejecutar. Producción/staging y hosts sin esa
  frontera fallan cerrados; no hay fallback inseguro ni cookies personales.
- `media.py`: helper explícito futuro de audio, separado de resolve, con
  FFmpeg/ffprobe, demuxing, whitelist y sandbox, 300 s/50 MiB, MP3 compacto y sin
  corte a 90 s. Solo se probó con audio sintético local y se eliminó al finalizar.
- `scripts/resolve_source.py`: CLI de desarrollo con resumen sin contenido en
  stdout y JSON privado 0600. `scripts/generate_evidence_contract.py` y
  `contracts/evidence-bundle.v1.{schema,manifest}.json`: snapshot/hash API, sin
  tocar RecipeDraft ni sincronizar Flutter. `tests/test_acquisition.py` y
  `tests/fixtures/acquisition/*`: fixtures propios, sin fallback runtime.
- `requirements.txt`, `requirements.lock`, `requirements-dev.lock`: únicamente
  Beautiful Soup 4.13.5, soupsieve 2.9.2 y yt-dlp 2025.9.26 añadidos y fijados.
  `.gitignore`: excepciones de fixtures JSON y exclusión de resultados locales.
  README y [guía Fase 05](phase05.md): operación, fuentes oficiales, matriz real.
- No se modificaron Flutter, SQL, migraciones, configuración de hosting ni la
  ruta legacy en esta fase. Se conservaron los cambios previos sin commit/reset.
  Comparación SHA-256 de **354 archivos de Flutter: sin cambios** durante Fase 05.

### Pruebas y resultados reales

| Comando/prueba | Resultado |
| --- | --- |
| `.venv-recovery/bin/python -m pytest -q` | **PASS, 74 tests (55 adquisición + 19 anteriores)**; 47 avisos de deprecación previos |
| `.venv-recovery/bin/ruff check src tests scripts` | PASS |
| Generadores `scripts.generate_evidence_contract --check` y `scripts.generate_contracts --check` | PASS, snapshots sin drift |
| `pip check`, `pip install --dry-run -r requirements-dev.lock` | PASS; dependencias fijadas coinciden con entorno |
| SSRF, DNS con respuestas mixtas, pinning/SNI, redirects a privadas/metadata/IPv6, gzip grande, timeout, cleanup/TTL y texto adversarial | PASS automatizado, sin red externa |
| yt-dlp real con broker de HTML sintético + sandbox real macOS | PASS; sin descarga del MP4 referenciado; no prueba plataformas reales |
| FFmpeg/ffprobe 8.0 reales | PASS: WAV sintético 2 s → MP3; límite de 1 s rechazado sin truncar; cleanup |
| `SourceResolver` contra `https://example.org` | PASS: TLS/fetch/parsing reales, 388 bytes recibidos / 559 descomprimidos; ninguna receta JSON-LD ni medios |
| CLI web real + social sin opt-in | PASS: códigos 0/2, estados ok/blocked, archivos 0600, `media_count=0`; archivos de prueba eliminados |
| Cinco fuentes públicas autorizadas del propietario | **NO EJECUTADO**: enlaces solicitados, no recibidos durante esta fase |
| YouTube/TikTok/Instagram/Facebook reales | **NO EJECUTADO**; producción **BLOCKED** hasta aislamiento probado en host objetivo |
| IA/STT/OCR/Whisper, llamadas pagadas, medios remotos, builds, despliegues, SQL/Supabase remoto | **NO EJECUTADO** |

La primera prueba de integración con yt-dlp falló por esperar el título literal
sin el sufijo `(1)` que añade su extractor HTML5. Se contrastó el resultado real
y se ajustó esa expectativa. Ruff detectó imports sin ordenar y se corrigieron.
Las ejecuciones finales anteriores sí pasaron; no se ocultan fallos como éxitos.

### Manual y siguiente punto de entrada

La [guía Fase 05](phase05.md#verificación-manual-exacta) contiene los cinco
comandos con URLs a sustituir, la matriz de soporte por fuente y los límites.
El propietario debe comparar la última frase de description/caption y cada
pista manual/automática con la fuente, verificar procedencia separada,
`media=[]` y `media_acquired_bytes=0`, y revisar warnings/truncamientos. Sin
subtítulos no debe aparecer transcripción inventada; sin análisis visual no
deben aparecer cantidades inventadas de pantalla.

Siguiente entrada: ejecutar esas cinco pruebas con enlaces autorizados y, antes
de habilitar redes sociales en un despliegue, implementar/probar aislamiento de
red equivalente allí. El piloto macOS no es prueba Linux/Nixpacks ni soporte
real de ninguna plataforma. No se implementó Fase 06 ni se requiere credencial
de IA para usar esta entrega.

Commit propuesto, **no ejecutado**: `feat: add evidence-first recipe source extraction`.

## Fase 04 · 2026-09-08

**Solo corrección de contrato y migración para integrar Flutter. Aplicado y verificado exclusivamente en Supabase local; sin cambios a endpoints de IA ni despliegue remoto.**

### Decisiones y archivos afectados

- `src/contracts/recipe_v1.py`: URL/plataforma de origen admiten `null`; las recetas manuales/legacy no inventan un origen. Contrato/snapshot/hash regenerados mediante `scripts.generate_contracts` y sincronizados al hermano Flutter. Añadido test de fuente manual desconocida.
- `supabase/migrations/20260908101632_phase04_cloud_operations.sql`: corrección aditiva de columnas, referencia privada de imagen, recibos idempotentes con RLS en esquema privado, `cloud_mutation_v1` y `library_snapshot_v1`. El wrapper usa `SECURITY INVOKER`, deriva owner de `auth.uid()` y conserva los RPCs de Fase 03. Revisión y conjunto esperado protegen ediciones/movimientos concurrentes; crear en colección y borrar receta/asociaciones son transacciones únicas.
- La migración original `20260907152033_create_recipe_contract_v1.sql` no se editó ni eliminó. La nueva función se iteró en local durante esta fase, incluyendo rollback de asociación inicial. No hubo reset de base, borrado de datos legacy/buckets ni desactivación de RLS.
- `supabase/config.toml`: callback local de Auth. `supabase/tests/database/03_cloud_operations.test.sql`: replay de alta/edición, conflicto y clave reutilizada, rollback de movimiento, asociaciones y recibos A/B. `docs/database/schema-v1.md`: contratos de RPC y rollback operacional sin pérdida.

### Pruebas y resultados reales

| Comando/prueba | Resultado |
| --- | --- |
| Supabase CLI y destino | PASS: CLI 2.110.0; proyecto local `foodiefy_api`, contenedor `supabase_db_foodiefy_api`, API 127.0.0.1:54321 y PostgreSQL 54322. |
| `supabase start`, `supabase db push --local` | PASS; migración aplicada al local existente, sin reset. |
| `python -m scripts.generate_contracts --check` | PASS: schema/manifest sin drift y snapshot Flutter sincronizado. |
| `.venv-recovery/bin/python -m pytest -q` | **PASS, 19 tests**. Persisten 47 avisos de deprecación del runtime previo. |
| `.venv-recovery/bin/ruff check src tests scripts` | PASS. |
| `supabase test db --local supabase/tests/database` | **PASS, 50 tests** en la ejecución final de SQL. |
| Advisors all y lint local con fallo ante warning | PASS, sin incidencias ni errores de schema. |
| Flutter contra Auth/PostgREST/Storage locales | **PASS, 1 test HTTP real**: incluye reapertura, revisiones, rollback creación/asociación, CRUD de colecciones, privacidad Storage y A/B/logout. Ver `foodiefy/tool/test_supabase_local.py`. |
| Staging/producción, `db push --linked`, reset remoto, IA/pagos, builds | **NO EJECUTADO**. |

Los tests HTTP crearon cuentas y datos sintéticos locales; no rescataron datos del propietario. La primera ejecución del arnés Flutter falló por PKCE sin storage y se corrigió; las pruebas finales sí pasaron. RLS no se deshabilitó para probar.

### Operación manual y siguiente entrada

La [guía Flutter de Fase 04](../../../foodiefy/docs/recovery/phase04.md) explica entorno local, callback, confirmación de cuenta, backup/checksum, revisión y reanudación. Desde el hermano API ejecutar solo `supabase start`, `supabase db push --local` y los gates anteriores. Reiniciar el stack local si estaba iniciado antes del cambio de callback. Cualquier promoción remota exige mostrar y autorizar específicamente el entorno/proyecto. Rollback: cliente en rescate/lectura y conservar tablas/recibos/fotos/backups; cualquier retirada exige otra migración forward y exportación verificada.

Siguiente punto: verificación manual nativa de Fase 04 por el propietario. No se implementa ninguna fase posterior.

Commit propuesto, **no ejecutado**: `fix: complete transactional cloud persistence contract`.

## Fase 03 · 2026-09-07

**Contrato v1 y Supabase reconstruible implementados y probados solo en local. No se continúa a Fase 04.**

### Decisiones y contratos

- `foodiefy_api` es la única fuente de verdad para Pydantic, JSON Schema y
  migraciones. El `supabase link` existente en el hermano Flutter se conservó;
  no se ejecutó operación remota ni se creó una segunda carpeta de migraciones.
- `RecipeDraft` y `RecipeRecord` están separados. El borrador rechaza identidad,
  propietario y campos extra; el registro añade UUID, owner, revisión, auditoría
  y tombstone. JSON `snake_case`, `schema_version="1.0"` y endpoint de lectura
  `GET /api/v1/contracts/recipe-draft`.
- Contrato generado en `contracts/recipe-draft.v1.schema.json`, manifest con
  SHA-256 y cinco fixtures válidos/erróneos. El generador valida drift y copia el
  snapshot al hermano sin editarlo a mano.
- Desconocidos son `null`; decimales finitos, rangos y posiciones se validan.
  Nutrición por ración exige raciones, y `per_100g` calculada/estimada exige masa
  conocida. Procedencia y estimación se distinguen.
- Migración CLI oficial `20260907152033_create_recipe_contract_v1.sql`: recetas,
  ingredientes, pasos, colecciones y relaciones privadas con claves compuestas
  por owner, índices para FKs/cursores, `numeric(18,6)`, RLS y grants mínimos.
  “Todas” permanece virtual; no existen catálogo público ni `user_recipes`.
- `save_recipe_v1`/`delete_recipe_v1` son `SECURITY INVOKER`, bloquean escrituras
  REST directas, controlan revisión, hacen replay idempotente y no resucitan
  tombstones. Fallar un hijo revierte la operación completa.
- Bucket `recipe-images` privado, tipos/tamaño limitados y policies por ruta
  `owner_id/...`. No se añadió `service_role` a Flutter.
- Jobs, shopping y suscripciones quedan documentados como contratos futuros sin
  tablas, colas, realtime, workers ni monetización.

### Pruebas reales

| Comando/prueba | Resultado |
| --- | --- |
| Supabase CLI `--help` y versión | PASS; CLI 2.110.0, Docker 28.1.1 |
| `.venv-recovery/bin/python -m scripts.generate_contracts --check` | PASS; schema/manifest sin drift |
| `.venv-recovery/bin/python -m pytest -q` | **PASS, 18 tests**; contrato, nulls, decimales, rangos, no finitos, identidad y baseline de Fase 01 |
| `.venv-recovery/bin/ruff check src tests scripts` | PASS |
| `supabase db reset --local` | **PASS** desde base desechable: migración + seed sintético |
| `supabase test db --local supabase/tests/database` | **PASS, 37 tests**; objetos/RLS, A/B, relaciones, transacción, replay, owner/revisión, tombstone y Storage |
| Advisors security/performance + `supabase db lint --local --level warning` | PASS; sin issues ni errores de schema |
| PostgREST/Storage HTTP local con dos cuentas sintéticas | **PASS**: RPC 200; A lee 1/B 0; PATCH B afecta 0; owner y revisión directos A 403; imagen A 200/B 400; upload cruzado B 400 |
| IA real, pagos, descarga masiva, builds de app/contenedor | **NO EJECUTADO** |
| `db push`, migración/reset remoto, staging/producción | **NO EJECUTADO** |

La primera ejecución pgTAP falló por un CTE de escritura inválido y reveló que
el contexto interno de RPC duraba hasta finalizar la transacción. Se corrigió
cerrándolo dentro de cada función y sustituyendo el CTE por medición de filas;
las dos ejecuciones completas finales pasaron. La primera descarga local recibió
`Rate exceeded` transitorios de Docker registry, se recuperó y terminó.

### Operación manual y siguiente punto de entrada

Seguir [schema-v1.md](../database/schema-v1.md): `supabase start`, `supabase db
reset --local`, pgTAP, advisors y lint. El propietario debe repetir la prueba con
dos cuentas de prueba y una cantidad decimal antes de autorizar staging. No usar
`--linked`; toda promoción futura requiere autorización explícita y revisión del
destino sin secretos.

Lo disponible ahora es el contrato versionado, RPCs y almacenamiento privado en
Supabase local. Flutter todavía no consume esas tablas/RPCs; esa integración,
caché y rescate pertenecen a Fase 04.

Commit propuesto, **no ejecutado**: `feat: define recipe contract and secure database schema`.

## Fase 01 · 2026-09-07

**Baseline local implementado y probado. No se continúa a Fase 02.**

### Conservación e inventario

Copia completa de los dos repositorios, Git, cambios y entorno `.venv` previo en `/Users/umartin-/Desktop/SprayNPray/FoodiefyBackup-20260907-161829`. El `.env` previo se conservó sin imprimirlo ni cargarlo en el runtime base. No hubo Git en el padre, commits, resets, builds ni despliegues. El MASTER_PLAN previo se leyó y conservó. No existía `progress.md` anterior. El propietario enlazó Supabase en el hermano Flutter durante esta ejecución; no se hicieron operaciones remotas.

| Archivo/contrato | Inventario inicial | Decisión aplicada |
| --- | --- | --- |
| `src/config.py` | BaseSettings, dotenv implícito, defaults genéricos DATABASE_URL/SECRET_KEY | Config tipada `APP_ENV`, flags legacy apagados; clave opcional SecretStr, sin dotenv implícito ni secretos ficticios. |
| `src/fastapi_app.py` | FastAPI global, imports Whisper/yt_dlp/TextBlob/Gemini y `VideoTranscriber()` global cargando modelo | Factory `create_app(settings=None)`, instancia de compatibilidad `app`, health sin dependencias externas. |
| Rutas | `POST /api/analyze-recipe`, `GET /api/health` | Se conserva POST, apagado devuelve HTTP 503 JSON explícito. Health nuevo `GET /health/live` devuelve 200 `{"status":"ok"}`; `/api/health` no se conserva. |
| `src/legacy_adapter.py`, `src/legacy_fastapi.py` | Implementación histórica mezclada con arranque | Adaptador importa legacy solo tras opt-in local explícito, key y presupuesto declarado. Whisper se carga al transcribir, nunca al importar el módulo nuevo. Gemini antiguo no se repara. |
| `requirements.txt` | FastAPI 0.110.1, Uvicorn standard 0.29.0, Flask/TextBlob/yt_dlp/Gemini/Whisper Git flotante | Runtime mínimo con FastAPI/Uvicorn conservados, Pydantic fijado. Separación dev/legacy. |
| `requirements.lock`, `requirements-dev.lock` | No existían | Resolución transitiva fijada del entorno limpio probado; runtime no incluye test/linter/IA. |
| `requirements-legacy.txt` | Dependencias pesadas en base | Extra histórico separado, versiones directas exactas, Whisper 20250625 publicado. No instalado ni lock transitivo validado. |
| `nixpacks.toml` | Python 3.12 + ffmpeg, instala Torch y descarga corpus | Solo Python 3.12 y requirements.lock, comando factory Uvicorn. Build/hosting NO EJECUTADO. |
| `pyproject.toml`, `tests/test_rescue.py`, README, `.env.example` | Tests vacíos y arranque ligado al legacy | pytest, Ruff fijado, ejemplos sin secretos y comandos de rescate. Lint excluye explícitamente dos referencias históricas. |

No se intentó arrancar el módulo histórico original para evitar carga/descarga de Whisper. Ese fallo de diseño está comprobado en fuente (`VideoTranscriber` inicializado a nivel de módulo y `whisper.load_model` en constructor); no se presenta como una ejecución de arranque antigua.

### Pruebas reales

| Comando/prueba | Resultado |
| --- | --- |
| `python3 --version` y entorno nuevo | Python 3.14.0 macOS arm64; `.venv-recovery` independiente, `.venv` previo intacto |
| Instalación `requirements-dev.txt` y resolución de lockfiles | PASS; FastAPI 0.110.1, Uvicorn 0.29.0, Pydantic 2.12.5, Settings 2.2.1, HTTPX 0.28.1, pytest 9.0.2, Ruff 0.12.12 |
| `python -m pip install --dry-run -r requirements-dev.lock` | PASS: resolución coincide con entorno instalado |
| `python -m pip check` | PASS: sin dependencias rotas |
| `.venv-recovery/bin/python -m pytest -q` | **PASS, 8 tests**; subprocess sin keys, paquetes Whisper/Torch ausentes, health con conexiones externas bloqueadas, rutas/configuración controladas |
| `.venv-recovery/bin/ruff check .` | **PASS**; `legacy_fastapi.py` y `flask_app.py` fuera del ámbito del linter |
| Uvicorn real `src.fastapi_app:create_app --factory` en loopback/puerto efímero | **PASS**: GET health 200 y POST import 503 `legacy_import_disabled`; proceso terminado tras prueba |
| `simctl spawn` en iPhone 17 / iOS 26.3 consultando ese health | **PASS**, loopback del Mac accesible; no se ejecutó la app Flutter |
| Nixpacks, Python 3.12, builds, contenedores, deployment | **NO EJECUTADO** |
| Legacy habilitado, IA real, modelos/medios, Supabase/RLS remoto | **NO EJECUTADO** |

pytest produce 33 avisos de deprecación en FastAPI/Starlette/AnyIO con Python 3.14. Se conservan las versiones de servidor directamente afectadas por el rescate; no se hace actualización masiva para silenciarlos. Las firmas de FastAPI TestClient y Uvicorn factory se contrastaron con la documentación oficial correspondiente a sus versiones.

### Límites y siguiente punto de entrada

Health solo prueba vida de la API. El legado requiere trabajo posterior y su presupuesto declarado es una condición de activación, no un contador que limite consumo. No hay mocks runtime ni éxito ficticio. La instalación del extra y su resolución transitiva quedan sin validar deliberadamente, fuera del arranque base.

Ejecutar el [README](../../README.md): iniciar sin keys, consultar `/health/live` y verificar el 503 esperado. Completar la comprobación manual del cliente del hermano. No habilitar IA ni ejecutar migraciones por el hecho de que el propietario haya creado/enlazado Supabase. La futura fase requiere una nueva instrucción.

Commit propuesto para este repositorio, **no ejecutado**: `chore: establish recoverable local baseline`.
