# Salud, alertas y limpieza

- GET /health/live: vida del proceso; sin DB/JWKS/IA. Esperado 200.
- GET /health/ready: configuración/JWKS confiable y acceso a tabla controls por
  rol backend, timeout DB 5 s y statement 10 s. Devuelve 503 genérico si falla;
  nunca imprime DSN. JWKS se cachea; no llama a OpenAI/Gemini.
- GET /ops/metrics: requiere X-Ops-Token, secreto de monitor. Ausente/incorrecto
  responde 404; sin DB 503. No es endpoint del móvil ni incluye contenidos/owners.
  Agrega queued/running/oldest_queued_seconds, expired_leases, failed_last_hour,
  live_workers, cleanup_pending, committed_usd, uncertain_charges, global_budget_usd,
  imports_enabled y paid_enabled. Cargos committed son máximo reservado/estimado/real
  por entrada, conservador; no sustituye factura del proveedor.
- Heartbeat worker en Postgres, incluidos periodos inactivos, y cada 10 s durante
  job. Se considera vivo hasta 90 s por defecto; IDs antiguos expiran a 7 días.
  Worker sin servidor HTTP/dominio; observar vía web protegida o DB admin.
- Logs HTTP: JSON de event/request_id UUID/route plantilla/status/duration_ms.
  Nunca body/query/Authorization, ni ruta literal con ID. Cabecera X-Request-ID
  inválida se sustituye. Uvicorn access log desactivado en entrypoint web.
- Logs worker: job_id, etapa, modelo y códigos cerrados; sin excepciones crudas,
  captions, URLs firmadas ni tokens. job_id relaciona intentos/ledger; request_id
  relaciona cada petición, no se afirma propagación de un request_id al worker.

Configurar manualmente alertas y receptores (no creados por Codex):

| Señal | Umbral inicial propuesto | Acción |
| --- | --- | --- |
| Liveness/readiness | 3 fallos consecutivos, intervalo 30 s | Revisar despliegue/TLS/DB/JWKS |
| live_workers | 0 durante 90 s con imports habilitados | Reiniciar worker, revisar DB |
| oldest_queued_seconds | >300 s durante 5 min | Revisar leases/concurrencia/kill switch |
| expired_leases | >0 persistente durante 2 leases | Revisar fencing y caída worker |
| errores HTTP 5xx | >2%/5 min con mínimo 20 requests | Revisar último cambio |
| latencia HTTP p95 | >2 s/5 min excluyendo health | Revisar DB y presión recursos |
| committed/global budget | 80% aviso, 95% urgente | Revisar/reservar presupuesto; gate DB impide exceder |
| uncertain_charges | >0 | No repetir cargo; reconciliar proveedor |
| cleanup_pending | >0 durante 10 min | Revisar collect y accesos DB |
| disk_pressure | cualquier evento sostenido | Reducir carga, revisar temporales/TTL/límite disco |
| gasto Railway/Supabase/IA | 50/80/100% del presupuesto acordado | Alertas de cada proveedor independientes |

Railway healthcheck solo actúa al desplegar. Para alertas continuas elegir el
monitor/log drain autorizado, configurar retención 14 días y acceso restringido,
comprobar entrega con fallo sintético. No se instaló Sentry/Prometheus/otro SaaS
ni se enviaron logs del usuario. Las métricas son muestra instantánea; el monitor
externo debe almacenar series y calcular tasas/p95. No hay alertas activas todavía.

job_directory limpia con finally tras éxito/fallo. Worker ejecuta colector de
huérfanos por TTL y respeta PID vivo; disco efímero no es almacenamiento del catálogo.
collect borra artifacts/cache expirados; tras cancelación conserva transcript y
recibos de respuesta pagada hasta TTL para evitar pagar otra vez. Una caída abrupta
requiere siguiente arranque/colector y lease; probarlo en Linux tras build manual.
El presupuesto de disco de 1 GiB y reserva mínima 256 MiB se deben verificar en
Railway. No descargar vídeos para una mera comprobación de salud.
