"""Validation and deterministic execution of company promotions. No AI calls."""
import math
import hashlib
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.business_settings import CompanyRule
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.schemas.rules import QuantityBonusConfig, RuleResponse, RuleWrite


def validate_rule_scope(db: Session, company_id: int, product_id: int | None, customer_id: int | None) -> None:
    if product_id is not None:
        product = db.get(Product, product_id)
        if not product or product.company_id != company_id or not product.active:
            raise ValueError("Product must be active and belong to this company")
    if customer_id is not None:
        customer = db.get(Customer, customer_id)
        if not customer or customer.company_id != company_id or not customer.active:
            raise ValueError("Customer must be active and belong to this company")


def validate_stored_rule(rule: CompanyRule) -> QuantityBonusConfig:
    if rule.rule_type != "quantity_bonus":
        raise ValueError(f"Unsupported stored rule type: {rule.rule_type}")
    return QuantityBonusConfig.model_validate(rule.configuration)


def rule_response(rule: CompanyRule) -> RuleResponse:
    return RuleResponse(
        id=rule.id, company_id=rule.company_id, rule_type="quantity_bonus",
        enabled=rule.enabled, product_id=rule.product_id, customer_id=rule.customer_id,
        configuration=validate_stored_rule(rule),
    )


def rule_fingerprint(product_id: int | None, customer_id: int | None, config: QuantityBonusConfig) -> str:
    canonical = json.dumps({
        "rule_type": "quantity_bonus", "product_id": product_id,
        "customer_id": customer_id, "configuration": config.model_dump(mode="json"),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_rule(db: Session, company_id: int, payload: RuleWrite) -> CompanyRule:
    validate_rule_scope(db, company_id, payload.product_id, payload.customer_id)
    fingerprint = rule_fingerprint(payload.product_id, payload.customer_id, payload.configuration)
    existing = db.execute(select(CompanyRule).where(
        CompanyRule.company_id == company_id, CompanyRule.fingerprint == fingerprint,
    )).scalar_one_or_none()
    if existing:
        existing.enabled = payload.enabled
        return existing
    rule = CompanyRule(
        company_id=company_id, rule_type=payload.rule_type, enabled=payload.enabled,
        fingerprint=fingerprint,
        product_id=payload.product_id, customer_id=payload.customer_id,
        configuration=payload.configuration.model_dump(mode="json"),
    )
    db.add(rule)
    db.flush()
    return rule


def evaluate_quantity_bonus(
    db: Session, company_id: int, customer_id: int, product_id: int | None,
    quantity: float, unit: str | None, customer_bonus: float,
) -> dict | None:
    """One line's paid quantity is the trigger; free goods never compound it."""
    if product_id is None or unit not in {"piece", "case", "kg", "pallet"}:
        return None
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Invalid order quantity for promotion")
    matches: list[tuple[CompanyRule, QuantityBonusConfig, float]] = []
    rules = db.execute(select(CompanyRule).where(
        CompanyRule.company_id == company_id,
        CompanyRule.enabled.is_(True),
        CompanyRule.rule_type == "quantity_bonus",
    ).order_by(CompanyRule.id)).scalars()
    for rule in rules:
        if rule.product_id is not None and rule.product_id != product_id:
            continue
        if rule.customer_id is not None and rule.customer_id != customer_id:
            continue
        config = validate_stored_rule(rule)
        trigger = config.trigger
        if trigger.unit != unit:
            continue  # No implicit conversion between units.
        ordered = Decimal(str(quantity))
        threshold = Decimal(str(trigger.quantity))
        reward = Decimal(str(config.reward.quantity))
        if trigger.mode == "per_quantity":
            award_value = (ordered // threshold) * reward
        elif trigger.mode == "greater_than":
            award_value = reward if ordered > threshold else Decimal(0)
        else:
            award_value = reward if ordered >= threshold else Decimal(0)
        if award_value > 1_000_000_000:
            return {
                "applied_rule_id": rule.id, "rule_type": "quantity_bonus",
                "rule_configuration": config.model_dump(mode="json"),
                "calculated_bonus_quantity": 0, "requires_review": True,
                "explanation": f"Rule #{rule.id} would exceed the supported free quantity; choose a final bonus.",
                "matching_rule_ids": [rule.id],
            }
        if award_value > 0:
            matches.append((rule, config, float(award_value)))
    if not matches:
        return None
    if len(matches) > 1:
        return {
            "applied_rule_id": None, "rule_type": "quantity_bonus", "rule_configuration": None,
            "calculated_bonus_quantity": 0, "requires_review": True,
            "explanation": f"Multiple promotion rules match ({', '.join(str(rule.id) for rule, _, _ in matches)}); choose the final free quantity.",
            "matching_rule_ids": [rule.id for rule, _, _ in matches],
        }
    rule, config, award = matches[0]
    conflict = customer_bonus > 0 and not math.isclose(customer_bonus, award)
    mode = config.trigger.mode
    description = (f"Every {config.trigger.quantity:g}" if mode == "per_quantity" else
                   f"Above {config.trigger.quantity:g}" if mode == "greater_than" else
                   f"At least {config.trigger.quantity:g}")
    explanation = (
        f"Rule #{rule.id}: {description} {unit} gives {config.reward.quantity:g} free {unit}. "
        f"Ordered {quantity:g} {unit} → calculated bonus {award:g} {unit}."
    )
    if conflict:
        explanation += f" Customer stated {customer_bonus:g} free {unit}; operator must choose the final bonus."
    return {
        "applied_rule_id": rule.id, "rule_type": rule.rule_type,
        "rule_configuration": config.model_dump(mode="json"),
        "calculated_bonus_quantity": award, "requires_review": conflict,
        "explanation": explanation, "matching_rule_ids": [rule.id],
    }


def effective_bonus(line) -> float:
    if line.final_bonus_quantity is not None:
        return line.final_bonus_quantity
    if line.bonus_quantity:
        return line.bonus_quantity
    return line.calculated_bonus_quantity or 0.0


def refresh_pending_promotions(db: Session, company_id: int) -> None:
    """Keep pending orders in the same transaction as a rule change."""
    from backend.app.models.order import Order
    from backend.app.schemas.workflow import OrderStatus
    from backend.app.services.order_workflow_service import OrderWorkflowService

    db.flush()
    orders = db.execute(select(Order).where(
        Order.company_id == company_id,
        Order.status == OrderStatus.PENDING_REVIEW.value,
    )).scalars()
    for order in orders:
        changed = False
        for line in order.lines:
            before = (
                OrderWorkflowService._promotion_basis(line.promotion_result),
                line.final_bonus_quantity, line.status,
            )
            OrderWorkflowService._refresh_promotion(db, order, line)
            changed |= before != (
                OrderWorkflowService._promotion_basis(line.promotion_result),
                line.final_bonus_quantity, line.status,
            )
        if changed:
            order.version += 1
