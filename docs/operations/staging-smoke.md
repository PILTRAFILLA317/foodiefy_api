# Matriz de hosting · 2026-09-08

Proyecto/ref/región/digest/URL staging: **no proporcionados ni provisionados**.
Build/deploy/restore: **NO EJECUTADOS**. Prueba macOS/SQL local no certifica datacenter.
No se anuncia soporte social/audio/visual con la barrera Linux actual.

| Caso | Resultado hosting | Condición antes de anunciar |
| --- | --- | --- |
| /health/live y /health/ready | NO EJECUTADO | DB TLS/JWKS y configuración real |
| JWT incorrecto GET /v1/imports →401 | NO EJECUTADO | Auth asimétrica real, sin crear jobs |
| Receta web Recipe JSON-LD | NO EJECUTADO | SSRF broker + fuente accesible desde IP hosting |
| Texto pegado sin proveedor configurado | NO EJECUTADO | Fallo controlado, sin éxito ficticio |
| YouTube narrado →STT | BLOCKED | Egress/sandbox Linux y runtime EJS/JS verificados; presupuesto explícito |
| TikTok / Instagram visual | BLOCKED | Igual, accesibilidad real y presupuesto visual |
| Facebook/social restante | BLOCKED | No asumir cookies/IP/browser personales |
| Fuente bloqueada / privada / metadata | NO EJECUTADO en hosting | Rechazo SSRF, sin acceso al destino |
| Cancelación de job | NO EJECUTADO | Estado cancelado y ninguna reserva posterior |
| Caída/reinicio worker | NO EJECUTADO | Mismo job/UUID, lease/fencing y sin repetir cargo uncertain |
| Limpieza éxito/fallo/SIGKILL/TTL | NO EJECUTADO | Disco/DB sin artefactos caducados persistentes |
| Restore de receta + imagen y RLS A/B | NO EJECUTADO | Lab aislado; runbook backup-restore.md |
| App desde datos móviles | NO EJECUTADO | HTTPS real, login/CRUD/import accesible |

Después del build y deploy manuales:

```sh
# STAGING_API_URL contiene solo la URL HTTPS pública revisada.
python -m scripts.smoke_staging
```

Este smoke solo hace GET de salud y JWT inválido; no carga fuentes ni paga IA.
Para cada prueba adicional registrar fecha UTC, SHA/digest, región, caso, job_id
sintético, PASS/FAIL/BLOCKED y código saneado. No registrar URL privada, texto,
headers, tokens ni resultados personales. Usar fuentes autorizadas y presupuesto
por prueba antes de activar proveedor. No ejecutar benchmark real en cada push.

Prueba de restart: desde la app staging enviar una fuente sintética/autorizada,
registrar job_id; con job running, propietario reinicia worker desde dashboard o
`railway redeploy --service worker`. Observar expiración de lease si SIGKILL,
reanudación con mismo ID y ledger, y que se conserva transcripción ya pagada. Las
reservas uncertain requieren reconciliación, no retry de pago automático. Cancelar
otro job en curso y verificar que no se toma una etapa nueva.

Prueba final propietario: con Wi-Fi apagado iniciar sesión/importar receta web;
revisar logs y gasto, repetir todas las plataformas **que se pretendan anunciar**
y restaurar backup con una imagen en lab. Si plataforma está bloqueada, retirar
su promesa del soporte, no cambiar gates para pasar el smoke.
