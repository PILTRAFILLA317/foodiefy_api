import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from scripts.generate_contracts import generated_files
from src.config import Settings
from src.contracts.recipe_v1 import RecipeDraft, RecipeRecord
from src.fastapi_app import create_app

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "contracts" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(), parse_float=Decimal)


def test_valid_fixture_preserves_decimals():
    draft = RecipeDraft.model_validate(load_fixture("recipe-draft.valid.json"))
    assert draft.ingredients[0].quantity == Decimal("1.5")
    assert draft.nutrition is not None
    assert draft.nutrition.kcal == Decimal("2100.5")


def test_unknown_values_remain_null():
    draft = RecipeDraft.model_validate(load_fixture("recipe-draft.valid-unknowns.json"))
    assert draft.prep_minutes is None
    assert draft.servings is None
    assert draft.ingredients[0].quantity is None
    assert draft.steps[0].duration_seconds is None
    assert draft.nutrition is None


@pytest.mark.parametrize(
    "fixture",
    [
        "recipe-draft.invalid-range.json",
        "recipe-draft.invalid-non-finite.json",
        "recipe-draft.invalid-per-serving.json",
    ],
)
def test_invalid_fixtures_are_rejected(fixture):
    with pytest.raises(ValidationError):
        RecipeDraft.model_validate(load_fixture(fixture))


def test_python_non_finite_number_is_rejected():
    payload = load_fixture("recipe-draft.valid-unknowns.json")
    payload["ingredients"][0]["quantity"] = float("inf")
    with pytest.raises(ValidationError):
        RecipeDraft.model_validate(payload)


def test_draft_cannot_receive_persisted_identity():
    payload = load_fixture("recipe-draft.valid.json")
    payload["id"] = str(uuid4())
    payload["owner_id"] = str(uuid4())
    with pytest.raises(ValidationError):
        RecipeDraft.model_validate(payload)


def test_record_adds_server_owned_fields_without_changing_draft_contract():
    payload = load_fixture("recipe-draft.valid.json")
    record_payload = deepcopy(payload)
    record_payload.update(
        {
            "id": str(uuid4()),
            "owner_id": str(uuid4()),
            "revision": 1,
            "created_at": "2026-09-07T12:00:00Z",
            "updated_at": "2026-09-07T12:00:00Z",
            "deleted_at": None,
        }
    )
    assert RecipeRecord.model_validate(record_payload).revision == 1
    assert "owner_id" not in RecipeDraft.model_json_schema()["properties"]


def test_generated_contract_files_are_current():
    for path, expected in generated_files().items():
        assert path.read_text() == expected


def test_versioned_contract_endpoint_matches_generated_schema():
    schema_path = ROOT / "contracts" / "recipe-draft.v1.schema.json"
    with TestClient(create_app(Settings())) as client:
        response = client.get("/api/v1/contracts/recipe-draft")
    assert response.status_code == 200
    assert response.json() == json.loads(schema_path.read_text())


def test_manual_source_accepts_unknown_url_and_platform():
    from src.contracts.recipe_v1 import RecipeSource

    source = RecipeSource(url=None, canonical_url=None, platform=None, creator=None, source_kind="manual")
    assert source.url is None
    assert source.platform is None
