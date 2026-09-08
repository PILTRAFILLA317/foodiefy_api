# Contrato RecipeDraft v1

`foodiefy_api` es la fuente de verdad. El modelo Pydantic está en
`src/contracts/recipe_v1.py` y genera `contracts/recipe-draft.v1.schema.json`.
El JSON público usa nombres `snake_case` y `schema_version = "1.0"`.

## Separación de confianza

- `RecipeDraft` es un resultado todavía no guardado. No admite `id`, `owner_id`,
  `revision` ni auditoría; `extra="forbid"` impide que la IA los introduzca.
- `RecipeRecord` amplía el borrador con `id`, `owner_id`, `revision`,
  `created_at`, `updated_at` y `deleted_at`, todos propiedad de persistencia.
- Los campos desconocidos de tiempos, raciones, cantidades, temperatura,
  timestamp y nutrición son `null`, nunca cero o un número extraído parcialmente.
- Posiciones de ingredientes y pasos empiezan en 1, son contiguas y no se
  duplican. `quantity_max` no puede ser menor que `quantity`.
- Una unidad es texto de evidencia; el contrato no afirma convertibilidad.
- `evidence_source` separa texto, audio, metadata, evidencia visual, edición
  manual e inferencia. Toda `ai_inference` debe marcar `is_estimated=true`.
- Nutrición `per_serving` requiere `servings > 0`. Una estimación/calculada
  `per_100g` requiere `known_mass_g`; los valores de etiqueta o manuales pueden
  conservar su base original. Los métodos calculados/IA con valores requieren
  `assumptions` explícitas. Los porcentajes de UI no forman parte del contrato.
- Decimales son finitos y se validan sin `float` persistente. Los fixtures cubren
  rangos, `NaN`, desconocidos y la ausencia de raciones.

## Regeneración y snapshot Flutter

Desde `foodiefy_api/`:

```sh
.venv-recovery/bin/python -m scripts.generate_contracts --check
.venv-recovery/bin/python -m scripts.generate_contracts --sync-flutter ../foodiefy/contracts
git -C ../foodiefy diff -- contracts
```

El manifest incluye versión, SHA-256 del schema y SHA-256 de cada fixture. El
snapshot móvil no se edita a mano; un diff después del comando es la revisión
del cambio contractual.

El API expone el mismo schema de lectura en
`GET /api/v1/contracts/recipe-draft`. La ruta histórica de importación no cambia
en esta fase y sigue deshabilitada por defecto.
