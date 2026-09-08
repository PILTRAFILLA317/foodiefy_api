# MASTER PLAN — Foodiefy recovery → production

**Versión:** 2.0 — 7 septiembre 2026  
**Repositorios:** `foodiefy` (Flutter) + `foodiefy_api` (FastAPI)  
**Decisión IA actual:** text-first. OpenAI `gpt-transcribe` para STT cuando haga falta + `gpt-5-nano` para extracción estructurada. Description/caption siempre acompaña al transcript. Gemini queda como fallback visual, no como ruta universal.

## 1. Principios de recuperación

1. Recuperar antes de reescribir. Flutter, FastAPI y Supabase se conservan.
2. Todo esquema de Supabase se versiona en Git mediante migraciones; no volver a depender de tablas creadas solo desde dashboard.
3. Las recetas antiguas de SharedPreferences se consideran datos a rescatar, no basura.
4. Ninguna cantidad/nutrición se inventa para “rellenar” una UI. Desconocido = null/warning.
5. La importación es un job de servidor duradero, no una petición HTTP que depende de tener la pantalla abierta.
6. La arquitectura IA se decide por coste **por receta útil y fiel**, no por precio nominal de un token.

## 2. Arquitectura objetivo

```text
Flutter
  │ JWT + Idempotency-Key
  ▼
FastAPI /v1/imports
  ▼
Postgres job queue (Supabase)
  ▼
Worker
  ├─ SourceResolver
  │   ├─ Recipe JSON-LD
  │   ├─ title/description/uploader
  │   ├─ manual/auto subtitles
  │   └─ audio/video temporal cuando haga falta
  │
  ├─ Ruta barata
  │   ├─ JSON-LD completo → mapping directo
  │   ├─ description/subtitles suficientes → GPT-5 nano
  │   └─ sin transcript suficiente → audio → gpt-transcribe
  │                                    + description → GPT-5 nano
  │
  └─ Solo si falta evidencia visual de forma justificada
      └─ Gemini multimodal (vídeo o frames)

RecipeDraft revisable
  ▼
Flutter editor
  ▼
Supabase recipes / ingredients / steps / collections
  ▼
Shopping list
```

## 3. Por qué description + transcript

En redes sociales es frecuente que el audio explique la preparación mientras la caption contiene cantidades exactas. Por ello:
- `gpt-transcribe` recibe el audio y contexto limitado, no la description completa como “texto esperado”;
- `gpt-5-nano` recibe **description y transcript por separado**, con procedencia;
- si hay conflicto se conserva warning; no se elige silenciosamente;
- si los subtítulos existentes son suficientes se evita pagar STT;
- si la description parece una receta completa puede probarse primero con Nano y evitar STT;
- solo se procesa vídeo visualmente cuando hay una razón concreta.

## 4. Coste de planificación, no benchmark

La referencia actual del proyecto para `gpt-transcribe` es **$0.0045/minuto**. Con el ejemplo de planificación de 1.000 tokens de entrada textual y 800 de salida en GPT-5 nano, la parte Nano ronda $0.00037 por receta con las tarifas usadas en este plan; un vídeo de 60 s transcrito + Nano sería ~**$0.00487 por receta / $4.87 por 1.000** antes de retries, fallback, hosting e impuestos.

Esto NO es una predicción de factura: description/transcript reales varían, los modelos/precios cambian y el uso observado debe leerse del proveedor. Se mantiene `COSTES_TEORICOS.json` únicamente para planificación.

El ahorro más importante no es cambiar $0.0001 de modelo: es evitar STT cuando JSON-LD/description/subtítulos ya contienen la receta y evitar vídeo multimodal cuando audio+caption bastan.

## 5. Modelo de datos objetivo

Supabase debe reconstruirse desde migraciones. Como mínimo:
- `recipes`: identidad de receta, owner, source, metadata, raciones/tiempos, timestamps;
- `recipe_ingredients`: orden, `raw_text`, nombre normalizado, quantity nullable, unit nullable, notes;
- `recipe_steps`: orden, texto y metadata opcional;
- `recipe_nutrition`: valores nullable, método y assumptions;
- `collections`;
- `collection_recipes`;
- `shopping_items`;
- tablas privadas/de servidor para import jobs, attempts, usage ledger y artifacts.

RLS obligatoria en tablas expuestas. El cliente nunca escribe owner efectivo, estado de jobs, saldo, precio o resultados de worker.

## 6. Fases

### Fase 0 — Manual: proteger
Copias de los dos repos, comprobar instalaciones antiguas y no borrar SharedPreferences. Crear rama de recuperación si se desea.

### Fase 1 — Codex: arranque reproducible
Config por entorno, eliminar localhost hardcodeado como release, UUID importado, macros ficticios, health sin cargar Whisper y aislamiento del legacy.

### Fase 2 — Manual: servicios
Crear proyecto Supabase nuevo (sin tablas manuales), preparar Supabase CLI/MCP, `OPENAI_API_KEY`; Gemini key opcional para fallback/benchmark. No meter secrets en Flutter/Git.

### Fase 3 — Codex: contrato + migraciones
RecipeDraft/ingredientes estructurados, schema reconstruible, RLS y tests de dos usuarios.

### Fase 4 — Codex: persistencia y rescate
Supabase fuente remota, caché local acotada, auth y migración segura de recetas legacy.

### Fase 5 — Codex: Evidence-first
Obtener JSON-LD/description/subtítulos antes de descargar audio/vídeo; seguridad SSRF.

### Fase 6 — Codex: IA
OpenAI STT + Nano como baseline; description siempre llega al extractor; Gemini solo VisualRecipeExtractor.

### Fase 7 — Codex + humano: benchmark
Medir Nano con/without description, gpt-transcribe+Nano, Luna, Gemini audio/vídeo y STT alternativo por cohortes. Fidelidad numérica primero.

### Fase 8 — Codex: jobs y gasto
Postgres queue, stages reales, transcript/artifacts reutilizables en retry, ledger por etapa y kill switches.

### Fase 9 — Codex: app/import/share
Import resumible, stages reales y recepción de enlaces desde iOS/Android.

### Fase 10 — Codex: lista de compra
Añadir manualmente o desde receta, cantidades/raciones y offline acotado.

### Fase 11 — Codex + manual: staging
Docker ligero sin Torch/Whisper, Railway API+worker, CI y observabilidad. Deploy lo hace el propietario.

### Fase 12 — Codex: production readiness
Seguridad, privacidad, export/borrado, accesibilidad y checklists.

### Fase 13 — Manual: beta/publicación
Entornos prod, firma, stores y rollout.

### Fase 14 — Opcional: monetización
Suscripciones reales y cuotas server-side solo después de validar el núcleo.

## 7. Reglas de IA en producción

- No existe un modelo “para todo”.
- JSON-LD fiable puede evitar IA.
- Description/caption es evidencia de primera clase y nunca se omite del extractor.
- `gpt-transcribe` no decide ingredientes; solo transcribe.
- GPT-5 nano no puede afirmar que vio un vídeo.
- Gemini visual solo se usa cuando la evidencia textual indica necesidad visual o el benchmark demuestra una política mejor.
- `null` > inventar.
- Máximo de llamadas pagadas y presupuesto por intento.
- Todo provider/model/prompt/schema/coste queda observable sin loguear contenido personal completo.

## 8. Definition of Done de producción

No considerar Foodiefy lista porque “funciona en el simulador”. Debe existir:
- schema recreable desde Git;
- aislamiento de usuarios verificado;
- recuperación tras cierre/reinicio;
- tests de idempotencia y retries sin repagar STT;
- importación real probada con webs + redes;
- métricas de coste/latencia/fidelidad;
- backup/restauración de DB y Storage comprobados;
- export/borrado de cuenta;
- no secrets en cliente;
- lista de compra estable;
- beta en dispositivos reales;
- límites de gasto.
