# Fase 06 · Pipeline text-first preparado para benchmark

Implementado únicamente en API. Se mantiene `RecipeDraft v1` sin cambios ni
snapshots nuevos en Flutter. No se ejecutó IA real ni Fase 07.

## Entrada y decisiones

`RecipePipeline.run(EvidenceBundle, AttemptState)` es la entrada de biblioteca;
`scripts.analyze_source` es la entrada manual. No hay endpoint público de gasto,
colas, Redis, Celery ni cambios SQL. Las interfaces están separadas:

- `Transcriber.transcribe(AudioEvidence) -> TranscriptResult`.
- `RecipeExtractor.extract(RecipeEvidence) -> AnalysisResult`.
- `VisualRecipeExtractor.extract(VisualEvidence) -> AnalysisResult`.

Secuencia real:

1. Una única Recipe JSON-LD con nombre, ingredientes e instrucciones se mapea
   directamente al contrato, sin key ni llamada pagada. Parseo conservador de
   cantidades decimales/rangos/unidades iniciales; el raw se conserva. Raciones
   ambiguas quedan null, tiempos se convierten solo cuando representan minutos
   enteros y no se inventa la base nutricional. Nutrición raw sigue en evidencia
   con warning cuando no se normaliza. Más de una receta requiere selección.
2. Subtítulos existentes, HTML web o caption con señales fuertes van al extractor
   textual. Caption rica permite un único intento inicial. `no_recipe` termina;
   una receta respaldada termina sin STT. Un partial solo por campos opcionales
   tampoco dispara audio.
3. Vídeo sin texto suficiente solicita medio explícitamente, prepara MP3 con
   FFmpeg y ejecuta STT una vez. El extractor post-STT recibe **la caption completa
   y el transcript en campos distintos**, junto a metadata y evidencias web.
4. Solo una decisión visual con razón concreta respaldada permite solicitar
   vídeo/frames y llamar a Gemini. No vuelve a entrar en fallback después de
   esa llamada. Si faltan key/flag/medio/presupuesto o persiste la insuficiencia,
   termina blocked/partial con motivo, sin inventar información.

El filtro visual contrasta razones con texto disponible: referencias a pantalla,
transcripción vacía/no útil y carácter visual de la fuente. Rechaza solicitudes
basadas solo en nutrición/raciones/tiempos opcionales. `ocr_frame_hint` está en el
contrato pero no se acepta como evidencia fabricada: Fase 05 no implementa OCR.
Los patrones ES/EN son conservadores; otras lenguas pueden terminar partial.

## Proveedores y fidelidad

`OpenAITranscriber` usa el SDK **openai 2.26.0**, endpoint
`/v1/audio/transcriptions`, baseline **gpt-transcribe**. La firma instalada acepta
model string y `extra_body`; se usa `extra_body.languages` cuando el idioma está
respaldado. No se envía `prompt`, caption ni transcripción esperada. Se conservan
texto, idiomas devueltos (o lista vacía), duración preparada, MIME, bytes, hash y
usage. Límite 25 MB para el archivo STT y 300 s; el MP3 del piloto es mono,
16 kHz, 64 kbit/s. No hay Whisper/Torch/Torchaudio en el runtime principal.

`OpenAIRecipeExtractor` usa Responses, **gpt-5-nano**, Structured Outputs,
`store=false`, truncamiento del proveedor desactivado, sin tools y sin temperature.
La fuente va únicamente en un mensaje user como JSON de datos. Las instrucciones
system son constantes. Se conserva la caption completa incluso con transcript
perfecto; si el conjunto excede `AI_MAX_INPUT_BYTES`, se devuelve
`evidence_context_limit` antes de pagar. No se recorta silenciosamente la caption.

`AnalysisResult v1` contiene `recipe|partial|no_recipe`, RecipeDraft nullable,
confidence nullable y explicación, warnings, missing_information, decisión/razones
visuales, citas por campo y conflictos. El JSON Schema del proveedor se deriva
del mismo modelo: subset estructural estricto, campos requeridos y sin propiedades
extra; la validación local conserva rangos, decimales, posiciones y todas las
invariantes de RecipeDraft. Refusal, salida incompleta o inválida producen códigos
controlados y no se reparan con llamadas adicionales no presupuestadas.

Las citas textuales se comprueban como subcadenas de su fuente; campos numéricos
no respaldados se eliminan y se marcan para revisión. Ingredientes/pasos sin
soporte requerido impiden entregar un borrador usable. Source/creator se fijan
desde la evidencia, no desde el modelo. Conflictos declarados conservan evidencia;
un detector conservador adicional reconoce discrepancias sencillas de cantidad
entre caption y transcript. La validación no demuestra equivalencia semántica
universal ni convierte las citas generadas en verdad. Requiere revisión humana.

**Confidence no está calibrada empíricamente todavía**: se identifica como señal
interna no calibrada y se explica su limitación. No se afirma calidad medida ni
que Nano sea el ganador. La calibración pertenece al benchmark autorizado de
Fase 07. Las citas visuales identifican el artifact suministrado; su fidelidad
visual debe comprobarla el propietario.

No se estima nutrición como efecto lateral. Una estimación que aparezca en una
salida se elimina con warning; source-label exige evidencia numérica y base
explícita. `invalidate_nutrition_after_edit(previous, edited)` invalida y marca
nutrición al cambiar ingredientes. Es un helper API; no modifica el editor Flutter.

## Gemini visual y medios

`GeminiVisualRecipeExtractor` usa REST HTTPS con HTTPX **0.28.1** y modelo
configurable, baseline de implementación **gemini-2.5-flash**. No importa SDK
Gemini ni activa Gemini al arrancar FastAPI. Se envía schema JSON, caption,
transcript y metadata separados de los artifacts. Thinking budget 0; se recoge
usage incluido reasoning si existe. La key va en cabecera, nunca en query/log.

Dos variantes implementadas para poder compararlas después:

- `frames`: seis JPEG seleccionados uniformemente, con timestamp y artifact ID,
  dimensiones máximas 512×512 respetando aspecto.
- `video`: MP4 reducido, máximo 512×512, 1 fps y sin pista de audio; evita volver
  a pagar interpretación del audio ya transcrito. La reducción puede perder
  texto breve en pantalla: no se declara una variante ganadora.

La validación revisa dimensiones JPEG y ffprobe para vídeo (duración, resolución,
fps y ausencia de audio). Total de artifacts ≤12 MB y solicitud inline <19 MB.
No se usa Files API ni se almacenan vídeos en un proveedor como artifacts
persistentes. FFmpeg/ffprobe se ejecutan bajo el aislamiento de Fase 05 y los
temporales se eliminan al salir del contexto, también ante excepción.

Solo al solicitar audio/visual se vuelve a consultar metadata de yt-dlp para
seleccionar un medio directo. Se prioriza audio-only de bajo bitrate y se limita
el fallback muxed/vídeo a 720p; no se descarga 4K para STT. Se rechazan manifiestos
HLS/DASH en esta implementación: no se cede la red a FFmpeg. URLs firmadas se
usan solo en memoria/IPC privado y vuelven a pasar por SafeFetcher. No llegan
al bundle, a la IA ni a logs.

**Bloqueo heredado de Fase 05:** redes sociales en producción/staging y medios
en hosts sin sandbox equivalente siguen bloqueados. El piloto de medios se ha
verificado en macOS; no acredita Linux/Nixpacks ni soporte real de YouTube,
TikTok, Instagram o Facebook. Un medio directo opcional debe ser público y
autorizado; no usar cookies personales ni enlaces privados autenticados.

## Presupuesto, retry y observabilidad

Tres condiciones obligatorias: `--allow-paid`, `--budget-usd > 0` y
`--confirm-paid`. Son autorización humana para ese intento, no flags de éxito
simulado. Sin ellas, o sin key del proveedor requerido, no se construye el
cliente de pago. JSON-LD determinista puede terminar sin IA de forma legítima.

`PaidSession` reserva una estimación conservadora antes de cada llamada: bytes
UTF-8 del input/schema/instrucciones como cota textual, output máximo configurado,
duración para STT y margen de tokens visuales para medios reducidos verificados.
El uso conocido liquida la reserva; un fallo sin usage mantiene la reserva y
deja el coste estimado como **null**, nunca cero. Modelos sin precio versionado
no pueden llamar. No se reintenta automáticamente en el SDK (`max_retries=0`).

Defaults: un intento textual inicial, un STT, una extracción post-STT y un
fallback visual. `AI_TRANSIENT_RETRIES=0`; se permite configurar 1 retry adicional
de extracción únicamente tras timeout/error de red/408/429/5xx transitorio y con
reserva disponible. No hay retry de STT en esta fase. Refusal/400/salida inválida
y llamadas ya exitosas no son reintentables dentro del intento.

Reutilizar **el mismo `AttemptState` y la misma `PaidSession`** conserva transcript,
decisiones y gasto al reintentar, liga el estado al contenido de fuente y evita
repetir STT. Un resultado completo se reutiliza. Ese estado es local, en memoria
y de un solo hilo: no es un ledger duradero ni coordinación entre procesos.
Reiniciar el CLI crea otro intento y otro presupuesto; persistencia/idempotencia
duradera y límites compartidos son Fase 08, no se simulan aquí.

`src/analysis/pricing.json`, versión **2026-09-08.standard.v1**, USD:

| Modelo | Input | Output | STT |
| --- | --- | --- | --- |
| gpt-transcribe | — | — | $0.0045/min |
| gpt-5-nano y snapshot 2025-08-07 | $0.05/1M tokens | $0.40/1M tokens | — |
| gemini-2.5-flash, texto/imagen/vídeo sin audio | $0.30/1M tokens | $2.50/1M tokens incluido thinking | — |

Es estimación de tarifa estándar, no factura ni promesa de gasto exacto; no
descuenta caché ni calcula impuestos/hosting. STT usa duración facturable del
proveedor cuando la devuelve; si no, identifica `prepared_audio_estimate` y
redondea segundos para estimación (no afirma que sea la unidad de facturación
real). No reutilizar tarifas de un modelo para otro sin verificación/versionado.

Cada etapa registra provider/model, latencia, input/output/reasoning tokens,
duración, coste nullable, reserva y estado. El CLI exporta además los campos
planos solicitados: `source_extract_ms`, `audio_extract_ms`, `stt_*`,
`extractor_*`, `visual_fallback_used/reason`, `visual_cost_estimate`, coste y
latencia totales, prompt/schema/pricing versions. La latencia total incluye
adquisición conocida y el intervalo del intento. No se guarda contenido en logs.

## Configuración y comandos manuales

Entorno de servidor; `.env` no se carga implícitamente. Configurar las keys por
el mecanismo privado local habitual y no enviarlas por chat ni imprimirlas.

| Variable | Default |
| --- | --- |
| `OPENAI_API_KEY` | ausente |
| `STT_MODEL` | `gpt-transcribe` |
| `RECIPE_EXTRACTOR_MODEL` | `gpt-5-nano` |
| `ENABLE_VISUAL_FALLBACK` | `false` |
| `GEMINI_API_KEY` | ausente |
| `VISUAL_MODEL` | `gemini-2.5-flash` |
| `AI_TIMEOUT_SECONDS` | `60` |
| `AI_MAX_OUTPUT_TOKENS` | `6000` |
| `AI_MAX_INPUT_BYTES` | `80000` |
| `AI_TRANSIENT_RETRIES` | `0` |

Desde `foodiefy_api`, comprobación sin gasto:

```sh
rtk proxy .venv-recovery/bin/python -m pip install -r requirements-dev.lock
rtk proxy .venv-recovery/bin/python -m pytest -q
rtk proxy .venv-recovery/bin/ruff check src tests scripts
rtk proxy .venv-recovery/bin/python -m scripts.generate_analysis_contract --check
rtk proxy .venv-recovery/bin/python -m scripts.generate_contracts --check
rtk proxy .venv-recovery/bin/python -m scripts.generate_evidence_contract --check
```

Un bundle guardado por el CLI de Fase 05 se puede analizar sin nueva adquisición:

```sh
rtk proxy .venv-recovery/bin/python -m scripts.analyze_source --bundle /tmp/foodiefy-jsonld.json --output /tmp/foodiefy-analysis-free.json
```

Sin flags de pago, solo el mapping determinista puede terminar; una ruta IA
devuelve blocked y cero requests. El CLI crea archivos 0600 de forma exclusiva y
rechaza sobrescribir un resultado **antes** de adquirir/pagar. stdout contiene
solo estado, contadores y costes; el archivo privado contiene resultado, métricas,
transcript y el input estructurado preparado para inspección. Ese input puede
existir aunque no se haya enviado por bloqueo; comprobar `stages/paid_requests`.
No publicar ese JSON ni usarlo como log de producción.

Las siguientes llamadas reales **NO se ejecutaron**. Sustituir los placeholders
por fuentes públicas autorizadas y pasarlas solo tras revisar/aceptar su gasto:

```sh
rtk proxy .venv-recovery/bin/python -m scripts.analyze_source --url '<URL_CAPTION_RICA>' --allow-local-social --allow-paid --budget-usd 0.05 --confirm-paid --output /tmp/foodiefy-caption-real.json
rtk proxy .venv-recovery/bin/python -m scripts.analyze_source --url '<URL_NARRADA>' --allow-local-social --allow-paid --budget-usd 0.05 --confirm-paid --output /tmp/foodiefy-narrated-real.json
rtk proxy env ENABLE_VISUAL_FALLBACK=true .venv-recovery/bin/python -m scripts.analyze_source --url '<URL_VISUAL>' --allow-local-social --visual-variant frames --allow-paid --budget-usd 0.25 --confirm-paid --output /tmp/foodiefy-visual-frames-real.json
```

Para la variante vídeo repetir únicamente con otra autorización/presupuesto,
`--visual-variant video` y otro output. No se ejecutan ambas variantes en cascada.
Si una plataforma no ofrece medio directo, `--audio-url '<URL_AUDIO_PUBLICO>'` o
`--video-url '<URL_VIDEO_PUBLICO_REDUCIDO>'` permiten un recurso conocido y
autorizado para benchmark; no lo descargan si el routing no lo solicita.

El propietario debe comprobar:

1. Caption rica: `stages` no contiene `stt` ni preparación de audio; caption
   completa en `extractor_input_data.description` y receta fiel a cantidades.
2. Narrada: un único STT gpt-transcribe, una extracción post-STT Nano y **ambos**
   campos `description` y `transcript` presentes, sin caption usada como prompt
   STT. Revisión de cantidades, rangos, unidades y warnings de discrepancia.
3. Visual: fallback únicamente con razón respaldada, una llamada como máximo,
   o `partial/blocked` cuando no puede obtener la información. No cantidades
   inventadas; comparar citas/artifacts con el vídeo original.
4. Refusal/salida incompleta, límites, ausencia de key o precio no dan éxito
   ficticio. Datos desconocidos quedan null; métricas desconocidas también.
5. Cambiar ingredientes mediante el helper invalida nutrición con warning.

## Evidencia ejecutada y límites

Tests sin Internet/pago: SDK OpenAI real sobre HTTPX MockTransport, payload STT y
Responses, caption/transcript separados, rutas baratas, retry y reutilización,
conflictos/nulls/no_recipe/partial/refusal/output inválido, límites de gasto,
Gemini REST simulado para vídeo/frames, schemas, CLI 0600 y retiro de legacy.
FFmpeg/ffprobe y sandbox reales sobre medios sintéticos locales prueban reducción,
resolución/fps/silencio, frames/timestamps y limpieza; no prueban proveedores.

Disponibilidad de modelos para la cuenta, aceptación real del schema por los
proveedores, fidelidad/calibración, costes facturados y fuentes sociales reales:
**NO EJECUTADO**. Tampoco builds, despliegues, migraciones ni Fase 07.

Fuentes oficiales consultadas y firmas contrastadas con el SDK instalado:

- [gpt-transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe),
  [transcripción de archivos](https://developers.openai.com/api/docs/guides/speech-to-text).
- [gpt-5-nano](https://developers.openai.com/api/docs/models/gpt-5-nano),
  [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
  [precios OpenAI](https://developers.openai.com/api/docs/pricing).
- [Gemini generateContent](https://ai.google.dev/api/generate-content),
  [vídeo](https://ai.google.dev/gemini-api/docs/video-understanding),
  [precios Gemini](https://ai.google.dev/gemini-api/docs/pricing).

Commit propuesto, no ejecutado:
`feat: add text-first recipe extraction with visual fallback`.
