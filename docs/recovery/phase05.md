# Fase 05 · Adquisición de evidencias sin IA

Implementación exclusiva de `foodiefy_api`, 2026-09-08. No añade un endpoint de
fetch público ni modifica la importación legacy. La entrada es `SourceResolver`
para integración posterior y un CLI local revisable. No implementa Fase 06.

## Evidencia disponible sin pagar transcripción/LLM

- Web: título, metadescripción, autor, idioma declarado, referencia de thumbnail,
  texto de `main`/`article`/body filtrado y cada Recipe JSON-LD por separado.
  Soporta objeto, array, `@graph`, pasos de texto/HowToStep/HowToSection,
  yield declarado, tiempos ISO 8601 y nutrición tal como aparece en la fuente.
  Calcula segundos solo para duraciones no ambiguas de días/horas/minutos/segundos;
  conserva el ISO original incluso cuando no puede convertirlo. No inventa
  raciones, unidades, nutrientes, cantidades ni RecipeDraft. Varias recetas
  requieren selección posterior: no se fusionan.
- Social: yt-dlp obtiene metadata y caption completa, después el adaptador
  adquiere subtítulos manuales y luego automáticos. `download=False`,
  `skip_download=True`, sin postprocesadores ni escritura de subtítulos por
  yt-dlp. El broker puede obtener páginas/API/manifiestos necesarios para
  metadata; no ejecuta el downloader de audio/vídeo. Algunas plataformas pueden
  pedir cookies, tokens de plataforma, impersonation o JS: esa ruta falla de
  forma explícita, sin pedir credenciales ni recurrir al legacy.
- Un vídeo narrado sin subtítulos solo aporta metadata/description. Un clip
  visual solo aporta indicios textuales cuando existen. No se infieren palabras
  del audio ni cantidades de los fotogramas. No hay OCR, STT, LLM ni Whisper.
- Las señales indican presencia de transcripción, unidades/cantidades, listas,
  vocabulario de cocina, estructura ingrediente/paso y referencias a pantalla.
  Los patrones ES/EN tienen fixtures; otros idiomas conservan sus evidencias,
  pero las heurísticas pueden no reconocerlas. No certifican una receta.

## Contrato e integración

Fuente tipada: `src/acquisition/models.py`. Snapshot y SHA-256 en
`contracts/evidence-bundle.v1.{schema,manifest}.json`; generación independiente
de RecipeDraft y sin copiar archivos a Flutter:

```sh
rtk proxy .venv-recovery/bin/python -m scripts.generate_evidence_contract --check
rtk proxy .venv-recovery/bin/python -m scripts.generate_contracts --check
```

`EvidenceBundle.schema_version="1.0"`, `trust="untrusted_source_data"`.
Descripción, HTML, recetas, subtítulos manuales y automáticos tienen campos y
`source_kind` separados. Los subtítulos conservan además el original temporizado
en `raw_text` (VTT/SRT/JSON3). JSON-LD guarda cada objeto Recipe raw con URLs
redactadas; no guarda scripts ajenos. El ID de proveedor aparece en `source_id`;
los IDs de cada Recipe permanecen en su raw. Idioma declara su procedencia
(`source` o `subtitles`), no una confianza inventada.

`canonical_url` usa la URL final del fetch, normalizada: elimina fragmento y
query salvo identificadores públicos `v`/`id`. No confía en el rel=canonical de
la página. Puede omitir parámetros necesarios para volver a abrir una web:
el consumidor debe conservar privadamente la entrada original si necesita
reintentar; no se registrará en logs. Thumbnail es solo referencia, no descarga.
URLs de transporte de subtítulos, cookies, cabeceras y formatos de reproducción
no se exportan. El contenido de una fuente sigue siendo dato no confiable;
el bundle de desarrollo puede contener texto sensible publicado por la fuente.

`content_hash` cubre evidencia/procedencia normalizada con JSON canónico; excluye
tiempos, estado, warnings y contadores. Los tamaños distinguen bytes recibidos,
descomprimidos, serializados y `media_acquired_bytes` (cero en resolve).
Los estados son `ok`, `partial`, `blocked`, `error`. Éxito de adquisición no
equivale a receta válida. Fallos son códigos estables sin mensajes del proveedor.

`context_view(bundle, max_chars)` produce registros de DATOS separados con
`original_chars`, `truncated` y warning `context_truncated`, sin alterar el bundle
completo. El presupuesto cuenta caracteres del texto, no tokens ni el envoltorio
JSON. La Fase 06 deberá imponer también su límite de tokens y mantener esos
registros fuera de instrucciones system/developer. El código no crea mensajes
de IA ni promueve instrucciones incluidas en una fuente.

## Límites y seguridad

`Limits` permite configurar: 300 s de duración, 50 MiB por medio, 2 MiB tanto de
HTML/metadata/subtítulo recibido como descomprimido, 5 redirects, 30 s por etapa,
24.000 caracteres de contexto y 6 pistas por tipo de subtítulo. No hay recorte a
90 s. Un vídeo que declara más duración conserva metadata y marca que omitió
subtítulos. Si no declara duración, conserva el desconocido; el helper de medios
exige duración comprobable con ffprobe antes de convertir. Pistas omitidas,
formatos no disponibles, errores y límites quedan explícitos.

Web y broker social usan `SafeFetcher`: solo HTTP/80 y HTTPS/443, sin userinfo,
controles, backslash ni scoped IPs. Valida todas las respuestas DNS A/AAAA;
bloquea IPs no globales, privadas, metadata/link-local, loopback, multicast,
reservadas y mecanismos IPv6 mapped/6to4/Teredo/NAT64. El socket conecta al
sockaddr numérico ya validado. HTTPS conserva SNI/hostname original y usa
`ssl.create_default_context()`; no hay segunda resolución ni proxies del entorno.
Cada redirect y cada URL de subtítulos/medios se valida de nuevo. No se reenvían
Authorization/Cookie; POST de metadata está limitado a 64 KiB y no se reproduce
en redirects. Compresión gzip se limita durante la descompresión; otros encodings
fallan. MIME HTML exige cabecera y contenido compatible; FFmpeg usa demuxing real.

Fetch (incluido DNS) y parsing HTML se ejecutan en procesos con timeout externo,
CPU, descriptores y tamaño máximo de archivos. No usan shell. El padre mata el
grupo ante timeout. Entorno mínimo, HOME/TMPDIR privados por job, sin `.env`,
keys ni proxy heredado. Temporales con nombres propios, permisos privados,
`finally` y TTL de una hora; el recolector no elimina jobs de un PID vivo ni
directorios ajenos. El colector se ejecuta al abrir un job; no es un daemon.

yt-dlp corre con **red denegada por el SO**, no solo con una validación inicial de
URL. En macOS se comprueba que `sandbox-exec` rechaza conexión a un listener local.
Su único RequestHandler envía peticiones por un pipe privado al padre, que usa
SafeFetcher; máximo 30 peticiones y deadline global de metadata. No hay cookies
personales, plugins/configuración CLI cargada ni mensajes de fuente en stdout
de la aplicación. El pipe interno no se vuelca a logs.

**Producción/staging: social deshabilitado siempre. Linux/Windows: también
bloqueado en local**, sin fallback a yt-dlp libre. Falta implementar y verificar
una frontera equivalente en el host de despliegue. El piloto macOS no acredita
aislamiento en Nixpacks ni soporte de las plataformas.

`media.acquire_audio(url)` es un context manager separado, jamás llamado por
resolve/CLI. Descarga solo la URL de medio explícitamente solicitada mediante
SafeFetcher; no selecciona ni descarga 4K. ffprobe/FFmpeg también exigen el
sandbox, restringen protocolos a `file,pipe` y formatos, rechazan duración
desconocida/excesiva y producen MP3 mono, 16 kHz, 64 kbit/s sin truncar. MP3 se
elige como formato compacto de preparación; no se ha elegido/integrado un SDK
STT en esta fase. Referencias expiran al salir del job. FFmpeg/ffprobe **8.0**
del Mac se conservan; no se instalan durante resolve. Nixpacks no fue modificado
ni construido y esta ruta queda bloqueada allí. El helper no contiene selección
automática de formatos sociales ni descarga rutinaria de medios.

## Matriz de soporte real

| Fuente/ruta | Evidencia ejecutada en este entorno | Estado honesto |
| --- | --- | --- |
| Fetch HTTPS web | `https://example.org`, respuesta HTML real, TLS, 388 bytes recibidos / 559 descomprimidos, cero medios | PASS transporte web; no es una receta |
| Recipe JSON-LD simple/array/@graph/secciones/múltiples | Fixtures propios y parsing en worker real | PASS automatizado; web Recipe del propietario NO EJECUTADA |
| Receta HTML sin JSON-LD | Fixture propio, filtrado DOM y señales EN | PASS automatizado; web del propietario NO EJECUTADA |
| yt-dlp + broker + sandbox macOS | yt-dlp 2025.9.26 real sobre HTML sintético servido por el broker; sin descarga del MP4 referenciado | PASS de integración local sintética; no acredita plataformas |
| YouTube | Adapter y fixtures de metadata/captions | NO EJECUTADO con vídeo real; producción BLOCKED |
| TikTok | Selección de extractor real yt-dlp, sin fixture específico de plataforma | NO EJECUTADO real; producción BLOCKED |
| Instagram | Selección de extractor real yt-dlp, sin fixture específico de plataforma | NO EJECUTADO real; producción BLOCKED |
| Facebook/fb.watch | Selección de extractor real yt-dlp, sin fixture específico de plataforma | NO EJECUTADO real; producción BLOCKED |
| Narrado sin captions / clip visual | Fixtures propios, sin inventar transcripción/ingredientes | PASS automatizado; vídeos del propietario NO EJECUTADOS |
| Audio explícito | WAV sintético de 2 s → MP3 con FFmpeg real, rechazo de límite de 1 s, cleanup | PASS local; adquisición/conversión de medio remoto NO EJECUTADA |

No se recibieron los cinco enlaces autorizados durante la implementación. No se
anuncia ninguna red social como soportada. Los tests no salen a Internet ni
llaman a IA; las únicas conexiones del test de sandbox son listeners sintéticos
en loopback. El fetch manual a example.org se ejecutó aparte de pytest.

## Verificación manual exacta

Desde el repositorio API, conservar la carpeta existente y ejecutar:

```sh
rtk proxy .venv-recovery/bin/python -m pip install -r requirements-dev.lock
rtk proxy .venv-recovery/bin/python -m pytest -q
rtk proxy .venv-recovery/bin/ruff check src tests scripts
rtk proxy .venv-recovery/bin/python -m scripts.generate_evidence_contract --check
```

Sustituir cada `<URL_...>` por el enlace público propio/autorizado correspondiente.
No añadir cookies, tokens ni credenciales. Los archivos de salida deben ser
nuevos; el CLI rechaza sobrescritura y los crea con permiso 0600.

```sh
rtk proxy .venv-recovery/bin/python -m scripts.resolve_source '<URL_WEB_JSONLD>' --output /tmp/foodiefy-jsonld.json
rtk proxy .venv-recovery/bin/python -m scripts.resolve_source '<URL_WEB_HTML>' --output /tmp/foodiefy-html.json
rtk proxy .venv-recovery/bin/python -m scripts.resolve_source '<URL_VIDEO_DESCRIPCION>' --allow-local-social --output /tmp/foodiefy-description.json
rtk proxy .venv-recovery/bin/python -m scripts.resolve_source '<URL_VIDEO_NARRADO>' --allow-local-social --output /tmp/foodiefy-narrated.json
rtk proxy .venv-recovery/bin/python -m scripts.resolve_source '<URL_CLIP_VISUAL>' --allow-local-social --output /tmp/foodiefy-visual.json
```

Para pilotos lentos puede añadirse `--stage-seconds 60`; duración y contexto tienen
`--duration-seconds` y `--context-chars`. Todos los límites están disponibles en
`Limits` para uso como biblioteca. No hay flag para pagar IA ni para desactivar
el aislamiento. El CLI devuelve código 2 en blocked/error; partial conserva
lo adquirido y exige revisar warnings. Su stdout contiene solo contadores,
estado, timings y códigos; la descripción/subtítulos completos están únicamente
en el JSON privado. No subir esos archivos al repositorio ni a logs.

Abrir cada JSON localmente y comprobar físicamente:

1. `evidence.recipes` mantiene cada receta separada, ingredientes/pasos exactos,
   sección, yield y nutrición presentes en la web; desconocidos no se inventan.
2. `evidence.html.text` contiene el texto útil y no menús/scripts/publicidad
   reconocibles por el filtro. El filtro DOM es heurístico, no un navegador JS.
3. La última frase de caption está en `evidence.description.text`; manuales y
   automáticos aparecen en sus arrays con el `source_kind` correspondiente.
4. `evidence.media` es `[]`, `sizes.media_acquired_bytes` es `0` y stdout muestra
   `media_count: 0` en las cinco ejecuciones. No se crean audio/vídeo temporales
   durante resolve. Los jobs finalizados desaparecen del temporal del SO.
5. Sin captions no debe aparecer una transcripción inventada. Un indicio visual
   es solo una señal textual; no se deben inventar cantidades en pantalla.
6. Revisar warnings de omisión/error/truncamiento y comparar con la fuente.
   `context_data` puede estar truncado explícitamente; `evidence` conserva lo
   adquirido completo. Archivar el resultado de cada prueba como PASS/FAIL/
   BLOCKED sin convertir fixture PASS en soporte de plataforma.

## Fuentes oficiales verificadas

- [yt-dlp README 2025.09.26](https://github.com/yt-dlp/yt-dlp/blob/2025.09.26/README.md):
  `extract_info(..., download=False)`, skip-download y subtítulos separados.
- [yt-dlp RequestHandler/Response 2025.09.26](https://github.com/yt-dlp/yt-dlp/blob/2025.09.26/yt_dlp/networking/common.py):
  firmas de broker verificadas también contra el paquete instalado; el handler
  es una extensión ligada a esta versión y tiene test de integración real.
- [Python http.client](https://docs.python.org/3/library/http.client.html),
  [ssl](https://docs.python.org/3/library/ssl.html): conexión, contexto TLS/SNI.
- [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/bs4/doc/):
  parser HTML, selección DOM, `decompose`, `get_text`.
- [schema.org Recipe](https://schema.org/Recipe): campos y tipos de receta.
- [FFmpeg protocolos](https://ffmpeg.org/ffmpeg-protocols.html) y
  [opciones](https://ffmpeg.org/ffmpeg.html): whitelist, audio y metadata.

Dependencias nuevas fijadas: Beautiful Soup 4.13.5, soupsieve 2.9.2 transitiva,
yt-dlp 2025.9.26. Locks runtime/dev actualizados sin upgrade del resto.
Ningún SDK/modelo OpenAI/Gemini usado ni ninguna llamada pagada ejecutada.
