# Variables de staging · Fase 11

No copiar archivos .env a imagen/CI/app. Ningún ARG Docker recibe secretos.
No usar `railway config pull --include-variables`, `--show-values`, `set -x` ni
logs de cabeceras/cuerpos. Los secretos se introducen sellados por servicio.

| Variable | API web | Worker | App |
| --- | --- | --- | --- |
| APP_ENV | staging | staging | staging |
| LOCAL_RESCUE | — | — | false |
| API_BASE_URL | — | — | HTTPS público real de web |
| SUPABASE_URL | URL pública staging | misma URL | misma URL |
| SUPABASE_PUBLISHABLE_KEY | — | — | solo publishable/anon |
| IMPORT_DATABASE_URL | secreto DB login web | secreto DB login worker | **prohibido** |
| PGSSLROOTCERT | ruta CA de Supabase montada si necesaria | igual | prohibido |
| OPENAI_API_KEY | **no asignar** | secreto, solo al habilitar pago | prohibido |
| GEMINI_API_KEY | **no asignar** | secreto, visual actualmente bloqueado | prohibido |
| OPS_TOKEN | secreto exclusivo monitor | no necesario | prohibido |
| PORT | inyectado Railway, web escucha 0.0.0.0 | no URL pública | — |
| IMPORT_ENABLED | false inicial | false inicial | — |
| IMPORT_ALLOW_PAID | false | false inicial; doble gate con DB | — |
| IMPORT_ALLOW_LOCAL_SOCIAL | false obligatorio | false obligatorio | — |
| ENABLE_LEGACY_IMPORT / ENABLE_MOCKS / BYPASS_AUTH / ALLOW_INSECURE_HTTP | false obligatorio | false obligatorio | — |
| SUPABASE_JWT_SECRET | **no usar**, JWKS asimétrico | **no usar** | prohibido |
| ENABLE_VISUAL_FALLBACK | false | false | — |
| STT_MODEL / RECIPE_EXTRACTOR_MODEL / VISUAL_MODEL | mismos identificadores que worker | gpt-transcribe / gpt-5-nano / gemini-2.5-flash iniciales | — |
| IMPORT_MAX_DURATION_SECONDS | 300 máximo | igual | — |
| IMPORT_MAX_MEDIA_BYTES | 52428800 máximo | igual | — |
| AI_TIMEOUT_SECONDS | 60 | 60 (máximo 180) | — |
| AI_MAX_OUTPUT_TOKENS / AI_MAX_INPUT_BYTES | 6000 / 80000 | iguales | — |
| AI_TRANSIENT_RETRIES | 0 | 0; worker usa ledger de reintentos | — |
| WORKER_POLL_SECONDS | — | 2 (1–60) | — |
| WORKER_HEARTBEAT_MAX_AGE_SECONDS | 90 | 90 | — |
| IMPORT_MIN_FREE_DISK_BYTES | — | 268435456 | — |
| IMPORT_TEMP_TTL_SECONDS | — | 3600 | — |

Los modelos/límites que entran en policy_hash deben coincidir en API/worker. Al
cambiarlos, pausar admisiones y drenar/revisar jobs antiguos; no hacerles repetir
un gasto con otra política. IMPORT_ALLOW_PAID puede habilitarse por variable de
worker (requiere reinicio) y sigue requiriendo controls.paid_enabled y presupuesto.
Los flags CLI --allow-paid --confirm-paid conservan el opt-in de laboratorio.

`foodiefy_imports.controls` es el control dinámico de servidor: enabled,
paid_enabled, visual_enabled, worker_concurrency, active_per_user, daily_imports,
daily_stt, daily_visual, global_usd, user_daily_usd, job_usd, max_attempts,
lease_seconds, artifact_ttl_seconds y output_bytes. Su modificación es operación
administrativa revisada, no permiso del móvil ni del login backend. `enabled=false`
impide nuevas reservas y cancela en checkpoint; no puede deshacer una llamada ya
aceptada por un proveedor. global_usd es acumulado del ledger, no gasto mensual
Railway; reconciliar facturas externas por separado.

Crear logins distintos web/worker, sin superusuario/BYPASSRLS/CREATEDB/CREATEROLE,
miembros solo de `foodiefy_import_backend`. El código hace SET LOCAL ROLE y TLS
verify-full fuera de local. El rol existente es común a ambos procesos; no se
introduce separación SQL por método/API en esta fase. No usar postgres ni la clave
service_role como credencial de aplicación. Guardar/restaurar membership y CA por
runbook. El downloader recibe solo PATH/HOME/TMPDIR/LANG/PYTHONPATH mediante
minimal_env; no hereda DB, JWT, Ops ni ninguna clave de IA.

Storage recipe-images: privado, 10 MiB por imagen (revisar constraint vigente en
migración Fase 03), URLs firmadas de la biblioteca 3600 s; no vídeos en catálogo.
Importaciones limitan cuerpo a 8192 bytes, medios a 50 MiB y artifacts empaquetados
a 16 MiB. El límite de disco Railway propuesto es 1 GiB por servicio, sujeto a plan
real; configurar/confirmar su efectividad antes de activar carga pública.
