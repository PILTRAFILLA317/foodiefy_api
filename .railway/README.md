# IaC Foodiefy · staging solamente

SDK railway 3.11.0 fijado en package-lock; `npm ci --ignore-scripts` y `npm run check` no despliegan. CLI global 4.10.0 es demasiado antigua; usar CLI 5.49.6 según runbook.

Definición única api+worker, guard de proyecto/entorno, región/rama explícitas. preserve() exige variables selladas existentes. Nunca plan/apply en CI; nunca --show-values ni pull --include-variables. **Omitir un recurso puede borrarlo**: plan debe tener 0 destrucciones.

Ver ../docs/operations/deploy-rollback.md y variables.md. Proyecto, región real y presupuesto aún no seleccionados ni contratados.
