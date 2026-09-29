from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator


class BusinessSettingsValues(BaseModel):
    bonus_enabled: bool = False
    bonus_expression_mode: Literal["disabled", "paid_plus_bonus", "explicit_only"] = "disabled"
    unitless_order_behavior: Literal["require_review", "piece", "product_master_unit", "learned_product_preference"] = "require_review"
    allow_packaging_conversion: bool = False
    learn_unit_preferences: bool = False

    @model_validator(mode="after")
    def consistent(self):
        if not self.bonus_enabled and self.bonus_expression_mode != "disabled":
            raise ValueError("Bonus syntax requires bonus_enabled")
        if self.bonus_enabled and self.bonus_expression_mode == "disabled":
            raise ValueError("Choose a bonus expression mode when bonus is enabled")
        if self.unitless_order_behavior == "learned_product_preference" and not self.learn_unit_preferences:
            raise ValueError("Learned unit behavior requires learn_unit_preferences")
        return self


class BusinessSettingsResponse(BusinessSettingsValues):
    model_config = ConfigDict(from_attributes=True)
    company_id: int
