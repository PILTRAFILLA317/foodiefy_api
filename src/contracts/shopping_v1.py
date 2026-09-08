"""Shopping RPC input. Identity/audit/revision of records belongs to SQL."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from src.contracts.recipe_v1 import ContractModel


class ShoppingPayload(ContractModel):
    id: UUID
    revision: Annotated[int, Field(ge=0)] | None = None
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    raw_text: Annotated[str, Field(min_length=1, max_length=10000)] | None = None
    quantity: Annotated[Decimal, Field(gt=0, lt=1e12, allow_inf_nan=False)] | None = (
        None
    )
    quantity_max: (
        Annotated[Decimal, Field(gt=0, lt=1e12, allow_inf_nan=False)] | None
    ) = None
    unit: Annotated[str, Field(max_length=100)] | None = None
    preparation: Annotated[str, Field(max_length=500)] | None = None
    notes: Annotated[str, Field(max_length=10000)] | None = None
    checked: bool | None = None
    recipe_id: UUID | None = None
    ingredient_position: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.quantity_max is not None and (
            self.quantity is not None and self.quantity_max < self.quantity
        ):
            raise ValueError("range requires ordered known bounds")
        return self


class ShoppingOperation(ContractModel):
    operation_id: UUID
    kind: Literal["add", "edit", "checked", "delete"]
    payload: ShoppingPayload

    @model_validator(mode="after")
    def required_fields(self):
        if self.kind in {"add", "edit"} and self.payload.name is None:
            raise ValueError("name required")
        if self.kind == "add" and self.payload.raw_text is None:
            raise ValueError("raw snapshot required")
        if self.kind in {"edit", "delete"} and self.payload.revision is None:
            raise ValueError("expected revision required")
        if self.kind == "checked" and self.payload.checked is None:
            raise ValueError("absolute checked required")
        return self
