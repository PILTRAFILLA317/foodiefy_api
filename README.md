# Foodiefy API · Fase 08

La [Fase 08](docs/recovery/phase08.md) añade jobs autenticados en `/v1/imports`,
cola Postgres y worker separado, leases/fencing, artifacts reutilizables y ledger
con reservas por etapa. Pago y visual deshabilitados por defecto. Las dos nuevas
migraciones se aplicaron solo localmente; Flutter recibe el contrato de jobs,
sin integración móvil todavía. La guía incluye arranque y prueba de caída/retry.

La [Fase 07](docs/recovery/phase07.md) prepara el benchmark reproducible con 30
slots pendientes en [benchmarks/manifest.v1.json](benchmarks/manifest.v1.json),
presupuesto persistente, reanudación y revisión humana de fidelidad. El dry-run
ha ejecutado cero llamadas; no hay fuentes reales ni ganador medido.
La [decisión por cohorte](docs/ai/decision.md) sigue pendiente de medición.

FastAPI existente con contrato `RecipeDraft v1` y esquema Supabase privado,
reconstruible y probado localmente. La implementación IA histórica continúa
aislada; no se aplicó ninguna migración remota.

La [Fase 06](docs/recovery/phase06.md) añade el pipeline text-first con
`gpt-transcribe`, `gpt-5-nano` y Gemini visual opcional. JSON-LD completo evita
IA; description y transcript permanecen separados. El CLI
`python -m scripts.analyze_source` exige flag, presupuesto y confirmación para
cualquier llamada pagada. No se ejecutaron llamadas reales a proveedores ni se
eligió un ganador de benchmark. `RecipeDraft v1` y Flutter no cambian.

La ruta HTTP antigua ya no carga el stack legacy, incluso con los flags
históricos activados: devuelve `legacy_import_retired` cuando estaban completos.
El pipeline también se reutiliza desde el worker de jobs autenticados de Fase 08.
Las instrucciones antiguas de activación que se
conservan abajo son evidencia histórica, no una vía activa de ejecución.

La Fase 05 añade `SourceResolver` y `EvidenceBundle v1`: adquisición web segura,
JSON-LD, HTML, descripción y subtítulos separados, sin llamadas de IA ni descarga
automática de medios. Entrada de desarrollo: `python -m scripts.resolve_source`.
La [guía de Fase 05](docs/recovery/phase05.md) contiene los comandos, contratos,
límites y matriz de soporte real. Redes sociales deshabilitadas en producción;
el piloto macOS exige opt-in y aislamiento de red comprobado. Los apartados de
baseline siguientes conservan la evidencia histórica de las fases 01–03; el
estado actual y la integración Flutter de Fase 04 están en `progress.md`.

## Contrato y base local

- Contrato: [docs/contracts/recipe-draft-v1.md](docs/contracts/recipe-draft-v1.md)
- Esquema, seguridad y comandos: [docs/database/schema-v1.md](docs/database/schema-v1.md)
- Progreso/evidencia: [docs/recovery/progress.md](docs/recovery/progress.md)

Resumen de verificación de Fase 03:

```sh
.venv-recovery/bin/python -m scripts.generate_contracts --check
.venv-recovery/bin/python -m pytest -q
.venv-recovery/bin/ruff check src tests scripts
supabase db reset --local
supabase test db --local supabase/tests/database
```

El schema también está disponible en `GET /api/v1/contracts/recipe-draft`.
Guardar/editar/borrar recetas se hace mediante `save_recipe_v1` y
`delete_recipe_v1`; Flutter no los consume todavía en esta fase.

## Arranque reproducible

Verificado en macOS arm64 con Python **3.14.0**, FastAPI **0.110.1**, Uvicorn **0.29.0**, Pydantic **2.12.5**, HTTPX **0.28.1**, pytest **9.0.2** y Ruff **0.12.12**. El entorno `.venv` antiguo se conserva; se usa `.venv-recovery` independiente.

Desde `foodiefy_api/`:

```sh
python3 --version
python3 -m venv .venv-recovery
.venv-recovery/bin/python -m pip install -r requirements-dev.lock
.venv-recovery/bin/python -m pytest -q
.venv-recovery/bin/ruff check .
.venv-recovery/bin/python -m uvicorn src.fastapi_app:create_app --factory --host 127.0.0.1 --port 8000
```

Instalación inicial realizada desde requirements fijados; después se congeló la resolución transitiva en los lockfiles y se verificó con `pip install --dry-run -r requirements-dev.lock` y `pip check`. `requirements.lock` contiene solo runtime; `requirements-dev.lock` añade tests/linter. No instalan dependencias legacy. No se requiere `.env`: `Settings` lee el entorno del proceso, con valores seguros por defecto. `.env.example` es documentación, no contiene secretos ni se carga automáticamente.

En otra terminal:

```sh
curl --fail http://127.0.0.1:8000/health/live
curl -i -X POST http://127.0.0.1:8000/api/analyze-recipe -H 'Content-Type: application/json' -d '{}'
```

Resultados esperados y verificados mediante servidor Uvicorn real en puerto efímero:

```text
GET  /health/live         200  {"status":"ok"}
POST /api/analyze-recipe  503  {"success":false,"error":"legacy_import_disabled"}
```

La factory `create_app(settings=None)` permite configuración inyectada por test. Se conserva `src.fastapi_app:app` para compatibilidad de arranque. Health solo certifica vida del proceso: no afirma conectividad con proveedores. La ruta histórica del importador es `/api/analyze-recipe`; `/api/health` antiguo se sustituye por `/health/live`.

Para móvil físico, usa `--host 0.0.0.0` y la IP LAN del Mac en la misma Wi-Fi. Para simulador iOS usa `127.0.0.1`, y para Android estándar `10.0.2.2`. La conexión loopback desde iPhone 17 / iOS 26.3 se verificó con `simctl spawn ... curl`; no se ejecutó Flutter ni una prueba de móvil físico.

## Legacy aislado

`src/legacy_fastapi.py` conserva la implementación anterior como referencia temporal, con Whisper cargado solo cuando se solicita transcripción. `src/legacy_adapter.py` es la única entrada del nuevo runtime a ese módulo y lo importa bajo demanda. El entorno base no lo importa ni requiere sus SDK.

`ENABLE_LEGACY_IMPORT=false` por defecto devuelve 503 incluso para JSON mal formado, antes de procesar la entrada. La activación histórica requeriría entorno local, un presupuesto positivo declarado en `LEGACY_BUDGET_USD` y `GEMINI_API_KEY` exclusivamente de servidor; sin ello devuelve `legacy_import_not_configured`. Declarar ese importe es una condición de activación, **no un contador ni un límite de gasto implementado**. No se activó ni certificó esa ruta; no debe exponerse públicamente.

Las dependencias históricas directas están separadas y fijadas en `requirements-legacy.txt`, incluido Whisper por versión publicada en lugar de Git flotante. **No se instalaron, no hay lock transitivo validado del extra legacy y no se ejecutó IA ni descarga de medios/modelos.** Gemini antiguo no se ha reparado. No habilites este extra para comprobar health.

`nixpacks.toml` instala únicamente `requirements.lock`; elimina Torch, ffmpeg y las descargas de corpus del arranque base. Mantiene Python 3.12 de la configuración existente. **Nixpacks/Python 3.12 y builds/despliegues: NO EJECUTADOS**; la prueba local usa Python 3.14.0.

## Pruebas y límites

- 8 tests pytest: factory independiente, importación sin keys/paquetes legacy, health sin sockets externos, 503 explícito y configuración incompleta controlada.
- Ruff PASS sobre runtime y tests. Los dos archivos históricos `legacy_fastapi.py` y `flask_app.py` quedan explícitamente fuera de lint; no se afirman corregidos.
- 33 avisos de deprecación en FastAPI/Starlette/AnyIO con Python 3.14; pruebas PASS, sin actualización masiva de SDK.
- `pip check`: PASS. HTTP real local: PASS. Conexión desde simulador: PASS.
- Auth/RLS/Supabase, importación real, móvil físico y distribución: NO EJECUTADOS.

Estado, inventario y punto de entrada siguiente: [docs/recovery/progress.md](docs/recovery/progress.md). Se conserva el [MASTER_PLAN.md](docs/recovery/MASTER_PLAN.md); esta entrega termina en Fase 01.

Fuentes oficiales verificadas: [FastAPI 0.110.1 TestClient](https://github.com/fastapi/fastapi/blob/0.110.1/docs/en/docs/tutorial/testing.md), [Uvicorn 0.29.0 factory](https://github.com/encode/uvicorn/blob/0.29.0/docs/deployment.md).

Commit propuesto, no ejecutado: `chore: establish recoverable local baseline`.
