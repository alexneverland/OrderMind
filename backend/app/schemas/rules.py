"""Closed set of executable company rules and untrusted AI proposals."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.business_settings import BusinessSettingsValues

Unit = Literal["piece", "case", "kg", "pallet"]
TriggerMode = Literal["greater_than", "greater_or_equal", "per_quantity"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuantityTrigger(StrictModel):
    mode: TriggerMode
    quantity: float = Field(ge=0.000001, le=1_000_000_000, allow_inf_nan=False)
    unit: Unit


class QuantityReward(StrictModel):
    quantity: float = Field(ge=0.000001, le=1_000_000_000, allow_inf_nan=False)
    unit: Unit


class QuantityBonusConfig(StrictModel):
    trigger: QuantityTrigger
    reward: QuantityReward

    @model_validator(mode="after")
    def compatible_units(self):
        # Mixed-unit promotions need a proven packaging ratio; not in this rule type.
        if self.trigger.unit != self.reward.unit:
            raise ValueError("Promotion trigger and reward must use the same unit")
        return self


class RuleWrite(StrictModel):
    rule_type: Literal["quantity_bonus"] = "quantity_bonus"
    enabled: bool = True
    product_id: int | None = Field(default=None, gt=0)
    customer_id: int | None = Field(default=None, gt=0)
    configuration: QuantityBonusConfig


class RuleUpdate(StrictModel):
    enabled: bool | None = None
    product_id: int | None = Field(default=None, gt=0)
    customer_id: int | None = Field(default=None, gt=0)
    configuration: QuantityBonusConfig | None = None


class RuleResponse(RuleWrite):
    id: int
    company_id: int


class SettingsPatch(StrictModel):
    bonus_enabled: bool | None = None
    bonus_expression_mode: Literal["disabled", "paid_plus_bonus", "explicit_only"] | None = None
    unitless_order_behavior: Literal["require_review", "piece", "product_master_unit", "learned_product_preference"] | None = None
    allow_packaging_conversion: bool | None = None
    learn_unit_preferences: bool | None = None


class ExportPatch(StrictModel):
    bonus_separate_row: bool | None = None
    bonus_marker: str | None = Field(default=None, max_length=20)
    quantity_output_unit: Literal["source", "piece"] | None = None
    convert_case_using_pieces_per_case: bool | None = None
    profile_id: int | None = Field(default=None, gt=0)


class QuantityRuleDraft(StrictModel):
    configuration: QuantityBonusConfig
    product_reference: str | None = Field(default=None, max_length=150)
    customer_reference: str | None = Field(default=None, max_length=150)


class UnsupportedRule(StrictModel):
    text: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)


class RulesAnalysis(StrictModel):
    settings_patch: SettingsPatch = Field(default_factory=SettingsPatch)
    quantity_rules: list[QuantityRuleDraft] = Field(default_factory=list, max_length=20)
    export_patch: ExportPatch | None = None
    unsupported_rules: list[UnsupportedRule] = Field(default_factory=list, max_length=20)


class RuleCandidate(StrictModel):
    id: int
    label: str


class ResolvedQuantityRule(QuantityRuleDraft):
    product_id: int | None = None
    customer_id: int | None = None
    product_candidates: list[RuleCandidate] = Field(default_factory=list)
    customer_candidates: list[RuleCandidate] = Field(default_factory=list)


class RulesProposal(StrictModel):
    settings_patch: SettingsPatch = Field(default_factory=SettingsPatch)
    quantity_rules: list[ResolvedQuantityRule] = Field(default_factory=list, max_length=20)
    export_patch: ExportPatch | None = None
    export_profile_candidates: list[RuleCandidate] = Field(default_factory=list)
    unsupported_rules: list[UnsupportedRule] = Field(default_factory=list)


class AnalyzeRequest(StrictModel):
    description: str = Field(min_length=3, max_length=6000)


class ApplyProposalRequest(StrictModel):
    proposal: RulesProposal


def merged_settings(current: BusinessSettingsValues, patch: SettingsPatch) -> BusinessSettingsValues:
    return BusinessSettingsValues.model_validate({
        **current.model_dump(), **patch.model_dump(exclude_unset=True, exclude_none=True)
    })
