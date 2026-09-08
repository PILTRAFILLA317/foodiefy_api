# Fase 07 · Benchmark reproducible, pendiente de fuentes y gasto

## Estado de entrega

El propietario pidió explícitamente **30 slots pendientes, sin URLs/fixtures
inventados, sin descargar fuentes de terceros y sin llamadas pagadas**. El
manifiesto está preparado; los informes entregados son dry-run vacío de mediciones.
No hay ganador ni cambio de configuración de producción. Los tests sintéticos
son pruebas del runner, no casos reales ni evidencia de calidad del modelo.

**Archivo que hay que rellenar: `benchmarks/manifest.v1.json`.**

| Cohorte | Slots | Rutas previstas |
| --- | --- | --- |
| Web JSON-LD completo | `json_ld-01` … `05` | J: mapping determinista sin IA |
| Description con ingredientes/cantidades | `description-01` … `05` | A, B, C, D, E |
| Vídeos con subtítulos | `subtitles-01` … `05` | A, C, D |
| Vídeos narrados sin subtítulos | `narrated-01` … `05` | B, C, D, E |
| Información relevante solo visual | `visual-01` … `05` | C, F_frames, F_video |
| No receta | `no_recipe-01` … `05` | A, C, E |

No se ejecuta toda la matriz por defecto durante esta entrega. El CLI permite
seleccionar casos y rutas; empezar por 3–5 casos y ampliar solo a los finalistas.
No existe una cohorte adicional fuera de MASTER_PLAN.

## Rellenar fuentes y referencias

Cada slot tiene:

- `url` **o** `local_path`: una fuente autorizada. Rutas relativas al directorio
  del manifiesto; también se aceptan rutas absolutas. No poner cookies ni secretos.
- `origin`, `license`: procedencia y licencia/permiso concreto. La accesibilidad
  pública no equivale a autorización. `processing_allowed` debe ser `true` solo
  después de verificarla. El runner bloquea los slots pendientes.
- `reference_path`: JSON de evidencia esperada, preparado/revisado por el
  propietario **antes** de medir, según `benchmarks/reference.v1.schema.json`.
- `metadata_path`: opcional EvidenceBundle v1 para acompañar un medio local con
  título, caption y subtítulos auténticos. Sin metadata quedan ausentes; no se
  deducen del nombre del archivo.
- `audio_path`/`video_path` o `audio_url`/`video_url`: overrides opcionales para
  medios que no pueda adquirir el extractor. URLs siempre pasan por SafeFetcher.
  Deben tener la misma autorización del caso. No se descargan durante dry-run.

`local_path` acepta EvidenceBundle JSON de Fase 05 (también el wrapper `evidence`),
HTML local, o MP4/WebM/MOV/MP3/WAV/M4A/OGG propio. Un medio local puede servir para
STT o visual sin descarga; FFmpeg determina streams/MIME y aplica límites.
Para description/subtítulos locales, usar el bundle o `metadata_path` real.
Los medios no se copian al repositorio ni permanecen en temporales tras el job.
El archivo original aportado por el propietario nunca se borra.

Guardar contenido privado bajo `.benchmark-local/` (ignorado), por ejemplo
`reference_path: "../.benchmark-local/references/description-01.json"`.
El manifiesto público solo debería contener datos que puedan entrar a Git.
Si incluso las URLs/licencias son privadas, copiarlo a
`.benchmark-local/manifest.json` y usar `--manifest`; ajustar las rutas relativas.
Los slots versionados no contienen ninguna URL ni fixture de terceros.

La referencia tiene `schema_version: "1.0"`, `expected_status: "recipe"` o
`"no_recipe"`, `reviewer` y `facts`. Cada hecho incluye:

- `id` estable, `kind` (`ingredient`, `quantity`, `unit`, `step`, `temperature`,
  `time`, `servings`, `contradiction`), `value` literal esperado y `essential`.
- `output_path` relativo a RecipeDraft, por ejemplo `ingredients.0.quantity` o
  `steps.0.text`. Separar extremos de rangos (`quantity`/`quantity_max`) y la unidad
  en hechos distintos. La revisión puede alinear posiciones si el modelo reordena.
- `sources`: dónde está el dato en la fuente de referencia: `description`,
  `transcript`, `visual`, `subtitles`, `json_ld`, `html`. Se permiten varias.
  Anotar individualmente ingredientes y cantidades: no heredar la procedencia
  de toda la receta. `transcript` aquí describe narración esperada, no garantiza
  que STT la haya conservado; `observed_sources` de la revisión registra lo observado.

Una referencia de receta debe incluir ingredientes y pasos, todas las cantidades,
unidades, tiempos, temperaturas y raciones relevantes (también sus ausencias o
contradicciones al revisar). Para no-receta, `facts` puede estar vacío. No usar
salidas del modelo como referencia esperada ni enviar esta referencia al proveedor.

## Rutas y equidad de la comparación

- **J:** JSON-LD completo directo. No requests ni coste IA.
- **A:** description/subtítulos separados → `gpt-5-nano`.
- **B:** `gpt-transcribe` → Nano, sin description, subtítulos ni HTML/JSON-LD
  que puedan filtrarla. Es una ablación exclusiva del benchmark.
- **C:** description completa + mismo transcript → Nano, candidato principal.
- **D:** input textual byte a byte idéntico a C → `gpt-5.6-luna`, reasoning `low`.
  Nano conserva `minimal`; ambos fijan `service_tier=default` (tarifa estándar),
  usan Responses Structured Outputs, mismo schema,
  máximo de salida 6000 por defecto y mismas instrucciones de Fase 06.
- **E:** audio directo → `gemini-2.5-flash-lite`; caption retirada para medir
  audio-only. No STT independiente ni cascada de proveedores.
- **F_frames/F_video:** Flash-Lite con caption y transcript disponible, seis JPEG
  uniformes o MP4 silencioso de 1 fps, ≤512 px. F no fuerza STT; cuando reutiliza
  el transcript de C se atribuye ese coste a la ruta. Comparar ambas variantes
  en el mismo run después de C para que tengan el mismo texto.
- **G, Groq:** opcional, no implementado ni medido. No se asigna ventaja ni precio
  ficticio. Añadirlo requeriría un nuevo adaptador y verificación oficial explícita.

Flash-Lite 2.5 es el baseline económico estable aún listado oficialmente:
$0.10/M texto/imagen/vídeo, $0.30/M audio, $0.40/M output. También se consultaron
3.1 y 3.5: sus tarifas publicadas son mayores para esta comparación de extracción.
La elección de baseline **no** afirma fidelidad superior, ni que sea el modelo
más reciente. No se sustituye Nano ni Luna por otros modelos.

Se reutilizan los adaptadores de Fase 06. El único cambio en runtime es permitir
inyectar catálogo, esfuerzo de reasoning y tier al construir el adaptador; los defaults
y la configuración de producción no cambian. Gemini audio/Flash-Lite vive solo en
`benchmarks/`, sin nueva dependencia ni SDK de arranque.

Se guardan `analysis` original validado por schema y, para OpenAI,
`delivered_analysis` después del filtro de fidelidad de Fase 06. La puntuación
se hace sobre el original: un número inventado no desaparece del benchmark
porque el filtro de producción lo convierta en null. No se llama a otro LLM
para evaluar ni se envían referencias humanas como instrucciones de extracción.

## Presupuesto y reanudación

Runner CLI separado de FastAPI; SQLite local del benchmark, sin migraciones ni
ledger de producción de Fase 08. `--allow-paid`, `--confirm-paid` y presupuesto
positivo son obligatorios para ejecutar. `--allow-network` autoriza adquisición
remota; no reemplaza autorización de procesamiento ni pago. Dry-run no instancia
clientes, no resuelve DNS, no ejecuta FFmpeg ni toca proveedores, incluso si
accidentalmente recibe flags de pago.

Cada request reserva antes de enviarse y la reserva se confirma a disco. El
presupuesto global suma reservas conservadoras, **sin devolverlas** tras una
respuesta barata: puede parar antes del tope económico, nunca intenta gastarlo.
El gasto observado usa usage, no reservas; precios/usage desconocidos son null.
Las reservas cubren input/schema/instrucciones, salida máxima, audio y medios
reducidos. El catálogo se bloquea si lleva más de 30 días sin reverificar.
Un tope del proveedor es la protección complementaria frente a cambios de tarifa
u otra facturación externa; el runner limita sus requests según el catálogo,
no puede garantizar la factura de la cuenta ni gastos ajenos.

Lock exclusivo durante la ejecución, reserva persistida antes de red y resultados
por caso/ruta. B/C/D comparten un STT, que queda cacheado. La reanudación no vuelve
a pagar casos completados. Ante caída después de enviar una llamada sin respuesta
persistida, el estado queda incierto: **no reenvía**, conserva reserva y coste null.
Los errores quedan registrados por etapa y tampoco se reintentan automáticamente.
No borrar el ledger para "reintentar" una llamada incierta. Primero reconciliar
su gasto externamente; una nueva campaña exige una nueva autorización.

El run queda ligado a hashes de manifiesto, fuentes/referencias locales, código,
catálogo y límites. Cambiar cualquiera o aumentar el presupuesto dentro del mismo
run se rechaza. Para ampliar, seleccionar otros slots ya preparados del mismo
manifiesto sin editarlo; preparar los 30 antes del piloto. Con fuentes aún no
preparadas, iniciar después otra campaña y reconocer que será otro presupuesto.
Conservar siempre el directorio del run; reanudarlo con el mismo `--report-dir`.

Los reports/ledger contienen evidencias completas para revisión privada: directorio
0700 y JSON/SQLite 0600, ignorados por Git. stdout solo muestra modo y contadores.
No compartir estos artifacts sin revisión. El informe dry-run versionado solo tiene
IDs, bloqueos y tarifas públicas, sin fuentes. Los temporales multimedia usan
finally/TTL y la frontera de red de Fase 05, también para medios locales.

## Métricas y revisión

`results.json` contiene etapas provider/model/usage y `source_acquisition_ms`,
`audio_extract_ms`, `stt_ms`, `extractor_ms`, `visual_ms`, `visual_prepare_ms`,
`total_ms`, costes separados, estado técnico/schema/análisis, fallo por etapa,
input con procedencia y versiones. `wall_ms` mide el tiempo con caché; `total_ms`
reconstruye adquisición/preparación/requests de una ruta standalone, atribuyendo
STT compartido. p50/p95 usan interpolación lineal (n−1), incluidos fallos; no
confundir esos percentiles con un despliegue concurrente o caché de producción.

Coste por receta útil = suma de costes de **todos** los casos de una cohorte/ruta,
incluidos fallos, dividida por recetas revisadas y útiles. No-recetas correctas
se cuentan aparte; también existe coste por caso aceptado. Si cualquier coste
es desconocido, el agregado es null. El coste global observado cuenta cada llamada
una vez; las comparaciones standalone atribuyen STT a cada ruta. Las cascadas C+F
solicitadas incluyen ambos extractores y STT una sola vez. No hay retries ocultos.

El runner genera `review-template.json`. Copiarlo a `reviews.json` privado y
rellenar `reviewer`, `status_correct`, `human_correction_required`, todos los
hechos (`outcome: correct|omitted|changed`, `output_path`, `observed_sources`) y
contadores `invented` por tipo. Inspeccionar ingredientes/pasos extras, rangos,
unidades y números; **no** poner todos los contadores a cero por comodidad.
`observed_sources` refleja lo que realmente apareció en caption/transcript
suministrados o artifacts visuales, y puede ser `[]`. Hashes ligan la revisión
al resultado y referencia exactos; si cambian, la revisión queda inválida.

Las métricas guardan correctos/omitidos/cambiados/inventados por tipo y procedencia
`description|transcript|both|visual_only|other`. Comparaciones emparejadas B/C,
C/D, C/E y frames/vídeo, además de casos resueltos sin STT y solicitudes visuales.
Una solicitud visual es una señal del modelo, no verdad ni una medición humana
por sí sola. Los casos incompletos no se consideran éxitos de fidelidad.

Scoring legible: cobertura de hechos sobre 100, −25 por error grave, −5 por omisión,
−10 por cambio. Se conservan todos los contadores; la puntuación nunca sustituye
los umbrales. Número cambiado/inventado, unidad cambiada/inventada, ingrediente o
paso inventado son graves. La comparación determinista de números/unidades puede
revocar una marca humana "correcto" (15 ≠ 150, g ≠ kg); no convierte unidades
silenciosamente. Pasos y equivalencia semántica requieren juicio humano.

Para útil: éxito técnico/schema/estado, revisión completa, cero graves, todas las
magnitudes referenciadas presentes, ≥95% de ingredientes, ningún paso esencial
omitido y sin corrección humana. Para recomendar: ≥5 casos/ruta/cohorte, todos
revisados, ≥95% aceptados, cero graves y costes conocidos; después menor coste y
p95. Con cinco casos esto exige cinco aceptados. Recomendación siempre provisional;
no haber medido una ruta no la descarta. Sin muestra suficiente: **pendiente de medición**.

## Comandos exactos

Desde `foodiefy_api`, sin gasto:

```sh
rtk proxy .venv-recovery/bin/python -m benchmarks.runner --manifest benchmarks/manifest.v1.json --dry-run --report-dir reports/20260908T000000Z-dry-run
rtk proxy .venv-recovery/bin/python -m benchmarks.schema --check
rtk proxy .venv-recovery/bin/python -m pytest tests/test_benchmark.py -q
```

Después de rellenar fuentes y referencias, revisar primero el dry-run de 3 casos:

```sh
rtk proxy .venv-recovery/bin/python -m benchmarks.runner --manifest benchmarks/manifest.v1.json --cases description-01,narrated-01,visual-01 --routes A,B,C,D,E,F_frames,F_video --dry-run --report-dir reports/20260908T120000Z-pilot-plan
```

**No ejecutado ni autorizado en esta entrega.** Con keys configuradas de forma
privada, fuentes verificadas y autorización expresa futura del propietario,
el siguiente comando habilita el piloto con tope 0.50 USD (no objetivo de gasto):

```sh
rtk proxy .venv-recovery/bin/python -m benchmarks.runner --manifest benchmarks/manifest.v1.json --cases description-01,narrated-01,visual-01 --routes A,B,C,D,E,F_frames,F_video --report-dir reports/20260908T120000Z-pilot --allow-local-social --allow-network --allow-paid --confirm-paid --budget-usd 0.50
```

Cambiar el timestamp del directorio al de la campaña real y conservarlo. Para
fuentes exclusivamente locales omitir `--allow-network --allow-local-social`.
No todas las combinaciones seleccionadas están permitidas por cohorte; el runner
interseca la selección con `routes` del caso. No activar todos los modelos sobre
los 30 casos antes de revisar este piloto.

Reanudar: exactamente el mismo comando/directorio/presupuesto. Copiar la plantilla
para revisión manual:

```sh
rtk proxy cp -n reports/20260908T120000Z-pilot/review-template.json reports/20260908T120000Z-pilot/reviews.json
```

Tras rellenarla, regenerar informes **sin adquisición ni pago** y publicar solo
la decisión agregada en docs (no cambia producción):

```sh
rtk proxy .venv-recovery/bin/python -m benchmarks.runner --manifest benchmarks/manifest.v1.json --report-dir reports/20260908T120000Z-pilot --budget-usd 0.50 --report-only --reviews reports/20260908T120000Z-pilot/reviews.json --publish-decision
```

Ampliar a finalistas únicamente tras revisión/autorización: mismo directorio y
presupuesto si queda reserva y el manifiesto no ha cambiado, seleccionando otros
IDs/rutas con `--cases`/`--routes`. No usar otro directorio como mecanismo de
"resume": es otra campaña y puede volver a pagar.

## Verificación y límites

Tests sin proveedores reales: dry-run, permisos, presupuesto agotado, lock,
reanudación/coste incierto, datos separados B/C/D, SDK real con transporte simulado
incluido Luna low, REST Gemini audio y visual, percentiles/scoring/procedencia,
JSON válido visual sin revisión y FFmpeg/sandbox reales con medios sintéticos.
No hay URLs reales seleccionadas, llamadas pagadas, benchmark de calidad, builds,
despliegues, migraciones ni Fase 08. No se modificó Flutter/RecipeDraft.

Se hereda el bloqueo de redes sociales en producción/staging y la necesidad del
sandbox macOS para medios. Tener un adaptador no demuestra soporte real de
YouTube/TikTok/Instagram/Facebook ni disponibilidad de un modelo para la cuenta.
Los manifiestos HLS/DASH no se descargan por una vía insegura. Si una fuente no
puede adquirirse, el fallo de adquisición queda separado de STT/extracción.

Catálogo: `benchmarks/prices.v1.json`, fecha 2026-09-08, sin nuevas dependencias.
Fuentes oficiales verificadas:

- https://developers.openai.com/api/docs/pricing
- https://developers.openai.com/api/docs/models/gpt-5.6-luna
- https://developers.openai.com/api/docs/models/gpt-transcribe
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite
- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/audio

El propietario debe distinguir errores de adquisición, STT y extracción, revisar
físicamente todos los números/unidades y los artifacts originales, y solo después
considerar una recomendación por cohorte. Este documento no autoriza gasto.
