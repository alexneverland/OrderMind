import re
from sqlalchemy.orm import Session
from backend.app.core.text_normalizer import normalize_text
from backend.app.models.business_settings import CompanyBusinessSettings
from backend.app.schemas.business_settings import BusinessSettingsResponse, BusinessSettingsValues


def effective_business_settings(db: Session, company_id: int) -> BusinessSettingsResponse:
    stored = db.get(CompanyBusinessSettings, company_id)
    if stored:
        return BusinessSettingsResponse.model_validate(stored)
    return BusinessSettingsResponse(company_id=company_id)


def validate_order_quantity_policy(settings: BusinessSettingsResponse, quantity_text: str | None, bonus_quantity: float) -> None:
    # This is a conservative guard on an AI-produced quantity interpretation.
    # It never infers the paid or free quantity itself.
    plus_expression = bool(quantity_text and re.search(r"\d\s*(?:[^\d+]*?)\+\s*\d", quantity_text))
    words = set(normalize_text(quantity_text).split())
    explicit_free = bool(words & {"δωρο", "δωρεαν", "free", "bonus", "gift", "gratis"})
    if bonus_quantity and not settings.bonus_enabled:
        raise ValueError("Bonus quantities are disabled for this company")
    if plus_expression and settings.bonus_expression_mode != "paid_plus_bonus" and not (settings.bonus_expression_mode == "explicit_only" and explicit_free):
        raise ValueError("Paid + bonus syntax is not enabled for this company; review the quantity")
    if plus_expression and not bonus_quantity:
        raise ValueError("A paid + bonus expression was not extracted unambiguously")
    if bonus_quantity and not plus_expression and not explicit_free:
        raise ValueError("Bonus quantity lacks an explicit free-goods marker")
