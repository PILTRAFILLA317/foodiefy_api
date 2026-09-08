# Contratos generados

RecipeDraft v1 procede de `src/contracts/recipe_v1.py`; imports/evidence/analysis conservan sus generadores existentes.

Shopping v1 procede de `src/contracts/shopping_v1.py`. Desde API:

```sh
.venv-recovery/bin/python -m scripts.generate_shopping_contract --sync-flutter ../foodiefy/contracts
.venv-recovery/bin/python -m scripts.generate_shopping_contract --check --sync-flutter ../foodiefy/contracts
```

Schema y fixtures revisados tienen SHA-256 en manifest. El snapshot Flutter no se edita a mano. La semántica SQL/offline está en `docs/recovery/phase10.md`.
