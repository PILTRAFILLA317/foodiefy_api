# Deploy y rollback · exclusivamente operados por el propietario

## Estado y coste verificados el 2026-09-08

No se creó cuenta/proyecto, conectó repo ni desplegó. Proyecto Supabase de staging,
región real, presupuesto aprobado y dominios están pendientes. Railway local CLI
4.10.0 no tiene `config`; documentación vigente y npm publican CLI 5.49.6 y SDK
railway 3.11.0. SDK/TypeScript están fijados con lockfile en `.railway/` y typecheck.

Railway **no admite Config as Code en servicios nuevos**. `railway.json/toml` es
legacy y deja de leerse el 2026-12-01. Se entrega `.railway/railway.ts` (IaC GA),
no un railway.toml nuevo. `nixpacks.toml` se movió a `nixpacks.legacy.toml` en esta
carpeta como referencia; Dockerfile y builder DOCKERFILE son ahora explícitos.

Hobby: $5/mes con $5 incluidos, no dos servicios a precio fijo. Precios consultados:
RAM $10/GB-mes, CPU $20/vCPU-mes, egress $0.05/GB; Storage/DB/IA externos aparte.
Ejemplo presupuestario, **no medición**: 0.25 GB API + 0.5 GB worker y 0.1 vCPU
agregada constantes ≈ $9.50/mes más egress. Los límites propuestos de 1 GB y 1 vCPU
por servicio podrían llegar a ≈ $60/mes si ambos consumen el máximo continuamente.
Revisar coste, límites de plan y alertas de gasto antes de conectar/desplegar.

Región europea publicada: Amsterdam `europe-west4-drams3a`. Es candidata, no región
seleccionada: comprobar región real Supabase y disponibilidad de cuenta, latencia
de JWKS/DB/proveedor y residencia de datos. No afirmar cercanía a IA sin medición.

## Preparación y revisión

1. En Railway, el propietario crea un proyecto dedicado con entorno **staging**,
   revisa facturación y crea servicios vacíos `api` y `worker`. Desactiva autodeploy
   antes de conectar GitHub. Worker sin dominio ni proxy TCP, sin serverless/sleep.
2. Revisa y registra SHA del repo `PILTRAFILLA317/foodiefy_api` que incluye fases
   10/11 aún sin commit. No desplegar un remoto que todavía no contiene estos cambios.
3. Introduce variables selladas por servicio según variables.md. El IaC usa preserve()
   para valores existentes y no inventa claves. Falta de configuración da no-ready.
4. CLI actual, solo instalación local de herramienta por el propietario:

```sh
cd /Users/umartin-/Desktop/SprayNPray/FoodiefyWorkspace/foodiefy_api
npm --prefix .railway ci --ignore-scripts --no-audit --no-fund
npm --prefix .railway run check
npx --yes @railway/cli@5.49.6 login
npx --yes @railway/cli@5.49.6 link
```

Seleccionar explícitamente proyecto y entorno staging. Establecer variables **no
secretas** FOODIEFY_RAILWAY_PROJECT_ID, FOODIEFY_STAGING_BRANCH y
FOODIEFY_STAGING_REGION con los valores revisados, y ejecutar:

```sh
npx --yes @railway/cli@5.49.6 config plan
```

No usar --show-values. El guard del archivo rechaza otro proyecto/production.
El plan debe contener solo api/worker, **0 destrucciones** y ningún recurso ajeno.
IaC tiene semántica «omitir = borrar»; no aplicar esta definición a un proyecto que
contenga otros recursos. `config apply` puede provocar builds/costes; solo después
de revisión expresa por el propietario:

```sh
npx --yes @railway/cli@5.49.6 config apply
```

No se entrega CI de apply ni builds en push. Confirmar que ambos despliegues usan
Dockerfile y el mismo SHA; si se exige el mismo digest exacto, construir una vez,
publicar la imagen en un registro autorizado y configurar ambos desde ese digest.
Dos builds del mismo Dockerfile/SHA son la misma receta, no prueba del mismo digest.

## Build local y gate de contenedor (NO EJECUTADOS por Codex)

Python 3.14.0 slim-bookworm está fijado por digest OCI; apt usa snapshot Debian
20260901 y ffmpeg 7:5.1.9-0+deb12u1 (ffprobe incluido). Python usa wheels lockeadas,
sin Torch/Whisper y sin extras EJS/Deno de yt-dlp: soporte social Linux sigue cerrado.
No secretos en ARG/COPY. Usuario UID/GID 10001; contexto allowlist .dockerignore.

```sh
docker build --pull=false -t foodiefy-staging:reviewed .
docker run --rm --read-only --tmpfs /tmp:rw,nosuid,nodev,size=1g --cap-drop=ALL --security-opt no-new-privileges foodiefy-staging:reviewed python -m scripts.container_verify
```

El gate prueba no-root, herramientas, entorno mínimo y rechazo SSRF/social. No
certifica redes sociales ni egress completo de un host. Repetirlo desde la imagen
en Railway y registrar digest/región/fecha. Hasta tener barrera OS Linux probada,
YouTube/TikTok/Instagram/Facebook/audio/visual no se anuncian como soportados.
Web usa broker DNS/IP público fijado, límites de redirects/bytes/duración. Probar
además tests de SSRF en el host y revisar que no hay ruta alternativa sin broker.

Commands sobre **la misma imagen**:

```sh
python -m scripts.web
python -m src.imports.worker
```

Web escucha 0.0.0.0:$PORT y no crea workers. Worker no abre servidor HTTP; usa
Postgres leases/fencing/heartbeat, nunca BackgroundTasks ni Redis/Celery.

## Promoción de migraciones (manual, no en arranque)

Antes: backup independiente, revisar diff SQL y compatibilidad con clientes viejos.
Mostrar project ref no secreto en ticket de cambio. CLI 2.110.0, sin --db-url con
credenciales en argumentos:

```sh
supabase link --project-ref "$STAGING_PROJECT_REF"
supabase migration list --linked
supabase db push --linked --dry-run
```

Comprobar destino en dashboard y salida, revisar cada migración pendiente (incluidas
fases previas). Solo entonces propietario ejecuta `supabase db push --linked`.
No reset, seed ni reparación de historial automática. No `preDeploy` de SQL.
Fase 11 agrega solo heartbeat; desplegar expansión antes de worker nuevo. Mantener
/v1 y columnas previas. Contracción futura exige medir adopción móvil y otro plan.

## Rollback

Cerrar admisiones (IMPORT_ENABLED=false/controls.enabled=false), conservar receipts,
leases y ledger. Volver ambos servicios al SHA/digest anterior compatible; vigilar
jobs activos, esperar expiración de lease tras terminación abrupta, no reemitir
cargos uncertain. La columna/tabla aditiva permanece. Volver código no recupera
un DROP ni datos borrados; restauración requiere backup y reconciliación aparte.
No restaurar el lock vulnerable anterior en un servicio público sin evaluar riesgo.

Health Railway usa /health/ready solo para promover despliegues, no monitoriza
continuamente. Worker reinicio manual: `railway redeploy --service worker` (CLI
actual confirma). Registrar job_id sintético antes/después y comprobar que no
cambia ni duplica gasto. No habilitar presupuestos reales para demostrar reinicio.

Cloud Run solo alternativa futura: un worker que sondea Postgres no escala a cero
por cambiar de proveedor. Requeriría Cloud Tasks/Jobs u otro disparador duradero;
no se implementa en esta fase.

Fuentes: https://docs.railway.com/infrastructure-as-code,
https://docs.railway.com/infrastructure-as-code/reference,
https://docs.railway.com/reference/pricing/plans,
https://docs.railway.com/reference/regions,
https://docs.railway.com/guides/dockerfiles,
https://docs.railway.com/guides/healthchecks.
