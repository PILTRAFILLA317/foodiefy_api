from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

RequiredText = Annotated[str, Field(min_length=1, max_length=10_000)]
PositiveDecimal = Annotated[
    Decimal,
    Field(gt=0, max_digits=18, decimal_places=6, allow_inf_nan=False),
]
NonNegativeDecimal = Annotated[
    Decimal,
    Field(ge=0, max_digits=18, decimal_places=6, allow_inf_nan=False),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceKind(StrEnum):
    WEB_PAGE = "web_page"
    SOCIAL_POST = "social_post"
    VIDEO = "video"
    MANUAL = "manual"


class EvidenceSource(StrEnum):
    SOURCE_TEXT = "source_text"
    SOURCE_AUDIO = "source_audio"
    SOURCE_METADATA = "source_metadata"
    SOURCE_VISUAL = "source_visual"
    MANUAL = "manual"
    AI_INFERENCE = "ai_inference"


class NutritionBasis(StrEnum):
    WHOLE_RECIPE = "whole_recipe"
    PER_SERVING = "per_serving"
    PER_100G = "per_100g"


class NutritionMethod(StrEnum):
    SOURCE_LABEL = "source_label"
    CALCULATED = "calculated"
    AI_ESTIMATE = "ai_estimate"
    MANUAL = "manual"


class NutritionStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class RecipeSource(ContractModel):
    url: AnyHttpUrl | None
    canonical_url: AnyHttpUrl | None
    platform: RequiredText | None
    creator: RequiredText | None
    source_kind: SourceKind


class Ingredient(ContractModel):
    position: Annotated[int, Field(ge=1)]
    raw_text: RequiredText
    name: RequiredText
    quantity: PositiveDecimal | None
    quantity_max: PositiveDecimal | None
    unit: RequiredText | None
    preparation: RequiredText | None
    group: RequiredText | None
    evidence_source: EvidenceSource
    is_estimated: bool

    @model_validator(mode="after")
    def validate_range_and_provenance(self) -> Ingredient:
        if (
            self.quantity is not None
            and self.quantity_max is not None
            and self.quantity_max < self.quantity
        ):
            raise ValueError("quantity_max must be greater than or equal to quantity")
        if self.evidence_source is EvidenceSource.AI_INFERENCE and not self.is_estimated:
            raise ValueError("ai_inference evidence must be marked as estimated")
        return self


class Step(ContractModel):
    position: Annotated[int, Field(ge=1)]
    text: RequiredText
    duration_seconds: Annotated[int, Field(gt=0)] | None
    temperature_c: Annotated[
        Decimal,
        Field(ge=-100, le=500, max_digits=6, decimal_places=2, allow_inf_nan=False),
    ] | None
    source_timestamp_seconds: NonNegativeDecimal | None


class NutritionEstimate(ContractModel):
    basis: NutritionBasis
    kcal: NonNegativeDecimal | None
    protein_g: NonNegativeDecimal | None
    carbs_g: NonNegativeDecimal | None
    fat_g: NonNegativeDecimal | None
    method: NutritionMethod
    assumptions: list[RequiredText]
    status: NutritionStatus
    known_mass_g: PositiveDecimal | None

    @model_validator(mode="after")
    def validate_evidence(self) -> NutritionEstimate:
        values = (self.kcal, self.protein_g, self.carbs_g, self.fat_g)
        if self.status is NutritionStatus.UNAVAILABLE and any(
            value is not None for value in values
        ):
            raise ValueError("unavailable nutrition cannot contain nutrient values")
        if self.status is NutritionStatus.COMPLETE and any(
            value is None for value in values
        ):
            raise ValueError("complete nutrition requires all nutrient values")
        if (
            self.method in {NutritionMethod.CALCULATED, NutritionMethod.AI_ESTIMATE}
            and any(value is not None for value in values)
            and not self.assumptions
        ):
            raise ValueError("calculated or estimated nutrition requires assumptions")
        if (
            self.basis is NutritionBasis.PER_100G
            and self.method in {NutritionMethod.CALCULATED, NutritionMethod.AI_ESTIMATE}
            and self.known_mass_g is None
        ):
            raise ValueError("calculated per_100g nutrition requires known_mass_g")
        return self


class RecipeDraft(ContractModel):
    """Unpersisted extraction output; intentionally has no identity or owner."""

    schema_version: Literal[SCHEMA_VERSION]
    title: RequiredText
    description: RequiredText | None
    source: RecipeSource
    ingredients: Annotated[list[Ingredient], Field(min_length=1)]
    steps: Annotated[list[Step], Field(min_length=1)]
    prep_minutes: Annotated[int, Field(gt=0)] | None
    cook_minutes: Annotated[int, Field(gt=0)] | None
    total_minutes: Annotated[int, Field(gt=0)] | None
    servings: PositiveDecimal | None
    yield_text: RequiredText | None
    nutrition: NutritionEstimate | None
    warnings: list[RequiredText]

    @model_validator(mode="after")
    def validate_positions_and_nutrition_basis(self) -> RecipeDraft:
        expected_ingredients = list(range(1, len(self.ingredients) + 1))
        if [item.position for item in self.ingredients] != expected_ingredients:
            raise ValueError("ingredient positions must be contiguous and start at 1")

        expected_steps = list(range(1, len(self.steps) + 1))
        if [item.position for item in self.steps] != expected_steps:
            raise ValueError("step positions must be contiguous and start at 1")

        if (
            self.nutrition is not None
            and self.nutrition.basis is NutritionBasis.PER_SERVING
            and self.servings is None
        ):
            raise ValueError("per_serving nutrition requires servings greater than zero")
        return self


class RecipeRecord(RecipeDraft):
    """Persisted private recipe with server-owned identity and audit fields."""

    id: UUID
    owner_id: UUID
    revision: Annotated[int, Field(ge=1)]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


def recipe_draft_json_schema() -> dict:
    schema = RecipeDraft.model_json_schema()
    schema["$id"] = "https://contracts.foodiefy.app/recipe-draft.v1.schema.json"
    schema["title"] = "Foodiefy RecipeDraft v1"
    return schema
