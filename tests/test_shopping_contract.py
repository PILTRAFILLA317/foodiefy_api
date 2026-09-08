from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.contracts.shopping_v1 import ShoppingOperation


def test_manual_unknown_and_audit_rejected():
    payload = {
        "id": str(uuid4()),
        "name": "papel de cocina",
        "raw_text": "papel de cocina",
    }
    op = ShoppingOperation(operation_id=uuid4(), kind="add", payload=payload)
    assert op.payload.quantity is None
    with pytest.raises(ValidationError):
        ShoppingOperation(
            operation_id=uuid4(),
            kind="add",
            payload={**payload, "owner_id": str(uuid4())},
        )


@pytest.mark.parametrize("quantity,maximum", [(3, 2), (0, None), (float("inf"), None)])
def test_invalid_quantities(quantity, maximum):
    with pytest.raises(ValidationError):
        ShoppingOperation(
            operation_id=uuid4(),
            kind="add",
            payload={
                "id": uuid4(),
                "name": "sal",
                "raw_text": "sal",
                "quantity": quantity,
                "quantity_max": maximum,
            },
        )


def test_reviewed_fixture_recipes_and_unknowns():
    import json
    from pathlib import Path

    from src.contracts.recipe_v1 import RecipeDraft

    fixtures = json.loads(
        (Path(__file__).parents[1] / "contracts/shopping.v1.fixtures.json").read_text()
    )
    RecipeDraft.model_validate(fixtures["base_recipe"])
    unknown = RecipeDraft.model_validate(fixtures["unknown_recipe"])
    assert any(i.quantity is None for i in unknown.ingredients)
    assert fixtures["manual_products"] == ["papel de cocina"]
