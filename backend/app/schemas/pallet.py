"""Validated, inert configuration for profile-scoped pallet planning."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictPalletModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DedicatedGroup(StrictPalletModel):
    name: str = Field(min_length=1, max_length=100)
    product_ids: list[int] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_products(self):
        if any(value <= 0 for value in self.product_ids) or len(set(self.product_ids)) != len(self.product_ids):
            raise ValueError("Dedicated group product IDs must be positive and unique")
        return self


class AutomaticPallets(StrictPalletModel):
    max_weight_kg: Decimal | None = Field(default=None, gt=0, le=1_000_000)
    max_rows: int | None = Field(default=None, ge=1, le=10_000)
    row_count_mode: Literal["output_rows", "logical_product_lines"] = "output_rows"
    packing_strategy: Literal["sequential"] = "sequential"

    @model_validator(mode="after")
    def capacity(self):
        if self.max_weight_kg is not None and not self.max_weight_kg.is_finite():
            raise ValueError("Maximum pallet weight must be finite")
        return self


class PalletOutput(StrictPalletModel):
    layout: Literal["single_sheet_sections", "multi_sheet_workbook", "separate_workbook_per_pallet"] = "single_sheet_sections"
    show_pallet_title: bool = True
    repeat_headers: bool = False
    blank_rows_between_pallets: int = Field(default=1, ge=0, le=20)


class PalletConfig(StrictPalletModel):
    enabled: bool = False
    dedicated_groups: list[DedicatedGroup] = Field(default_factory=list, max_length=100)
    automatic_pallets: AutomaticPallets = Field(default_factory=AutomaticPallets)
    output: PalletOutput = Field(default_factory=PalletOutput)

    @model_validator(mode="after")
    def unique_membership(self):
        if self.enabled and self.automatic_pallets.max_weight_kg is None and self.automatic_pallets.max_rows is None:
            raise ValueError("At least one automatic pallet capacity is required")
        names = [group.name.strip().casefold() for group in self.dedicated_groups]
        if len(set(names)) != len(names):
            raise ValueError("Dedicated group names must be unique")
        members = [pid for group in self.dedicated_groups for pid in group.product_ids]
        if len(set(members)) != len(members):
            raise ValueError("A product may belong to only one dedicated pallet group")
        return self


class DedicatedGroupDraft(StrictPalletModel):
    name: str = Field(min_length=1, max_length=100)
    product_references: list[str] = Field(min_length=1, max_length=500)


class PalletProposalDraft(StrictPalletModel):
    enabled: bool = True
    dedicated_groups: list[DedicatedGroupDraft] = Field(default_factory=list, max_length=100)
    automatic_pallets: AutomaticPallets
    output: PalletOutput = Field(default_factory=PalletOutput)

    @model_validator(mode="after")
    def capacity(self):
        if self.enabled and self.automatic_pallets.max_weight_kg is None and self.automatic_pallets.max_rows is None:
            raise ValueError("At least one automatic pallet capacity is required")
        return self


class ResolvedProductReference(StrictPalletModel):
    reference: str
    product_id: int | None = None
    candidates: list[dict[str, int | str]] = Field(default_factory=list)


class ResolvedDedicatedGroup(StrictPalletModel):
    name: str
    products: list[ResolvedProductReference]


class ResolvedPalletProposal(StrictPalletModel):
    enabled: bool = True
    dedicated_groups: list[ResolvedDedicatedGroup] = Field(default_factory=list)
    automatic_pallets: AutomaticPallets
    output: PalletOutput = Field(default_factory=PalletOutput)

    @model_validator(mode="after")
    def capacity(self):
        if self.enabled and self.automatic_pallets.max_weight_kg is None and self.automatic_pallets.max_rows is None:
            raise ValueError("At least one automatic pallet capacity is required")
        return self
