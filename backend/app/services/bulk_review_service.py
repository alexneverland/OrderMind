"""Explicit bulk review of safe matches; never turn model confidence into learning."""
import math

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.core.text_normalizer import normalize_text, normalize_unit, is_quantity_grounded_in_span, is_unit_grounded_in_span
from backend.app.models.order import Order, OrderLine, OrderRevision
from backend.app.models.product import Product
from backend.app.models.memory import CompanyProductUnitPreference, CustomerProductAlias
from backend.app.services.business_settings_service import effective_business_settings, validate_order_quantity_policy
from backend.app.services.company_rule_service import evaluate_quantity_bonus, effective_bonus
from backend.app.services.confidence_scorer import AUTO_ACCEPT_THRESHOLD, AMBIGUITY_SCORE_MARGIN
from backend.app.services.order_workflow_service import OrderWorkflowService
from backend.app.services.packaging_resolver import resolve_product_packaging


class BulkReviewConflict(ValueError):
    pass


def _unsafe_reason(db, order, line, business, preferences, aliases):
    if not math.isfinite(line.confidence_score) or line.confidence_score < AUTO_ACCEPT_THRESHOLD:
        return "Confidence below 95%"
    product = line.matched_product
    if not product or not product.active or product.company_id != order.company_id or line.final_sku != product.sku:
        return "Product unavailable or changed"
    winner = next((c for c in line.candidates if c.rank == 1 and c.product_id == product.id), None)
    if not winner or any("Multiple strong product candidates" in reason for reason in line.confidence_reasons):
        return "Product match needs individual review"
    if any(c.product_id != product.id and c.score >= line.confidence_score - AMBIGUITY_SCORE_MARGIN for c in line.candidates):
        return "Competing product matches"
    alias_id = aliases.get(normalize_text(line.product_phrase))
    if alias_id is not None and alias_id != product.id:
        return "Customer alias points to another product"
    qty = line.final_quantity
    if qty is None or not math.isfinite(qty) or qty <= 0 or qty != line.requested_quantity:
        return "Quantity changed or invalid"
    unit = line.final_unit
    if line.unit_explicit:
        expected = line.requested_unit
    elif business.unitless_order_behavior == "piece":
        expected = "piece"
    elif business.unitless_order_behavior == "product_master_unit":
        expected = normalize_unit(product.unit)
    elif business.unitless_order_behavior == "learned_product_preference":
        expected = preferences.get(product.id)
    else:
        expected = None
    if unit not in {"piece", "case", "kg", "pallet"} or unit != expected:
        return "Unit requires individual review"
    compatible, package_id, _ = resolve_product_packaging(product, unit, line.product_phrase)
    if not compatible or package_id != line.matched_packaging_id:
        return "Packaging ambiguous or changed"
    if unit == "case" and (not line.matched_packaging or not line.matched_packaging.pieces_per_case or line.matched_packaging.pieces_per_case <= 0):
        return "Missing case conversion"
    if line.final_bonus_quantity is not None:
        return "Free quantity was manually changed"
    current = evaluate_quantity_bonus(db, order.company_id, order.customer_id, product.id, qty, unit, line.bonus_quantity)
    if (OrderWorkflowService._promotion_basis(current) != OrderWorkflowService._promotion_basis(line.promotion_result)
            or current and current.get("requires_review")):
        return "Promotion changed or conflicting"
    bonus = effective_bonus(line)
    if not math.isfinite(bonus) or bonus < 0:
        return "Invalid free quantity"
    try:
        validate_order_quantity_policy(business, line.quantity_text, line.bonus_quantity)
        if (normalize_text(line.original_text) not in normalize_text(order.raw_input)
                or not is_quantity_grounded_in_span(qty, line.original_text, order.raw_input, line.product_phrase, line.quantity_text, line.bonus_quantity)
                or not is_unit_grounded_in_span(line.requested_unit, line.raw_unit, line.unit_explicit, line.original_text, order.raw_input, line.product_phrase, line.quantity_text)):
            return "Quantity or unit unsupported by customer input"
    except ValueError:
        return "Quantity policy requires review"
    return None


def confirm_safe_lines(db: Session, order_id: int, company_id: int, expected_version: int):
    db.rollback()
    try:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        order = db.scalar(select(Order).where(Order.id == order_id, Order.company_id == company_id).options(
            selectinload(Order.lines).selectinload(OrderLine.candidates),
            selectinload(Order.lines).selectinload(OrderLine.matched_product).selectinload(Product.packagings),
            selectinload(Order.lines).selectinload(OrderLine.matched_packaging),
        ))
        if not order:
            raise LookupError("Order not found in this company")
        if order.status != "pending_review":
            raise BulkReviewConflict("Only pending orders can confirm safe matches")
        if order.version != expected_version:
            raise BulkReviewConflict("Order changed; reload before confirming safe matches")
        if db.get(OrderRevision, order.id):
            raise BulkReviewConflict("Use the unchanged-line recheck for revisions")
        business = effective_business_settings(db, company_id)
        preferences = dict(db.execute(select(CompanyProductUnitPreference.product_id, CompanyProductUnitPreference.unit).where(
            CompanyProductUnitPreference.company_id == company_id)).all())
        aliases = dict(db.execute(select(CustomerProductAlias.normalized_phrase, CustomerProductAlias.product_id).where(
            CustomerProductAlias.company_id == company_id, CustomerProductAlias.customer_id == order.customer_id,
            CustomerProductAlias.active.is_(True))).all())
        confirmed, skipped = [], []
        for line in order.lines:
            if line.status != "needs_review":
                continue
            reason = _unsafe_reason(db, order, line, business, preferences, aliases)
            if reason:
                skipped.append({"line_id": line.id, "line_number": line.line_number, "reason": reason})
            else:
                line.status = "confirmed"
                line.confidence_reasons = [*line.confidence_reasons, "Operator bulk confirmation: safe match checks passed"]
                confirmed.append(line.id)
        # No alias counters: selecting by machine confidence must not reinforce itself.
        if confirmed:
            order.version += 1
        db.commit()
        return {"confirmed_count": len(confirmed), "skipped": skipped, "version": order.version}
    except Exception:
        db.rollback()
        raise
