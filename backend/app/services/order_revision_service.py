"""Create an explicitly reviewed successor; never rewrite approval/export history."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.order import Order, OrderLine, OrderRevision
from backend.app.models.product import Product, Packaging
from backend.app.models.export import ExportProfile
from backend.app.services.order_workflow_service import OrderWorkflowService
from backend.app.services.packaging_resolver import resolve_product_packaging
from backend.app.services.company_rule_service import effective_bonus
from backend.app.services.business_settings_service import effective_business_settings, validate_order_quantity_policy
from backend.app.services.export_engine import convert_order_sheet_quantities, OrderExportError


class RevisionConflictError(ValueError):
    pass


def _unchanged_approved_line(db, line, frozen, snapshot, business, profiles, prior_product_id=None):
    """Trust the prior approval only while its product and business quantities hold."""
    product = db.get(Product, line.matched_product_id) if line.matched_product_id else None
    if (not product or not product.active or product.company_id != line.company_id
            or product.id != frozen.get("product_id", prior_product_id) or product.sku != frozen.get("sku")
            or line.final_sku != frozen.get("sku")
            or line.final_quantity != frozen.get("quantity") or line.final_unit != frozen.get("unit")
            or effective_bonus(line) != frozen.get("bonus_quantity", 0)
            or line.promotion_result and line.promotion_result.get("requires_review")
            or line.final_bonus_quantity is not None):
        return False
    compatible, package_id, _ = resolve_product_packaging(product, line.final_unit, line.product_phrase)
    if not compatible or package_id != line.matched_packaging_id:
        return False
    packaging = db.get(Packaging, package_id) if package_id else None
    ratio = packaging.pieces_per_case if packaging else None
    if line.final_unit == "case" and ratio != frozen.get("pieces_per_case"):
        return False
    try:
        validate_order_quantity_policy(business, line.quantity_text, line.bonus_quantity)
        # Pallet grouping/layout/weight changes are reviewed at final approval;
        # changed exported goods quantities still need a line review.
        for profile in profiles:
            old = snapshot.get("export_profiles", {}).get(str(profile.id))
            if profile.format != "order_sheet" or not old or old.get("format") != "order_sheet":
                continue
            before = convert_order_sheet_quantities(
                frozen["quantity"], frozen.get("bonus_quantity", 0), frozen["unit"], frozen.get("pieces_per_case"),
                old["quantity_output_unit"], old["convert_case_using_pieces_per_case"],
                snapshot["business_settings"]["allow_packaging_conversion"],
            )
            after = convert_order_sheet_quantities(
                line.final_quantity, effective_bonus(line), line.final_unit, ratio,
                profile.quantity_output_unit, profile.convert_case_using_pieces_per_case, business.allow_packaging_conversion,
            )
            if before != after:
                return False
    except (ValueError, OrderExportError, KeyError, TypeError):
        return False
    return True


def recheck_revision(db: Session, order_id: int, company_id: int) -> Order:
    """Single explicit action for revisions created before automatic carry-forward."""
    db.rollback()
    try:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        order = db.get(Order, order_id)
        link = db.get(OrderRevision, order_id)
        if not order or order.company_id != company_id:
            raise LookupError("Order not found in this company")
        if not link or order.status != "pending_review":
            raise RevisionConflictError("Only pending revisions can recheck unchanged lines")
        source = db.get(Order, link.source_order_id)
        snapshot = source.approved_snapshot
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("lines"), list):
            raise RevisionConflictError("Source approval snapshot is unavailable")
        frozen_lines = {item["line_number"]: item for item in snapshot["lines"]}
        source_lines = {line.id: line for line in source.lines}
        business = effective_business_settings(db, company_id)
        profiles = list(db.scalars(select(ExportProfile).where(ExportProfile.company_id == company_id)))
        for line in order.lines:
            if line.status != "needs_review":
                continue
            OrderWorkflowService._refresh_promotion(db, order, line)
            frozen = frozen_lines.get(line.line_number)
            original = source_lines.get(frozen.get("line_id")) if frozen else None
            if frozen and _unchanged_approved_line(
                db, line, frozen, snapshot, business, profiles,
                original.matched_product_id if original else None,
            ):
                line.status = "confirmed"
                line.confidence_reasons = ["Prior approval retained: product and business quantities unchanged"]
        order.version += 1
        db.commit()
        db.refresh(order)
        return order
    except Exception:
        db.rollback()
        raise


def create_revision(db: Session, source_id: int, company_id: int, request_key: str) -> Order:
    # Serialize only the short SQL phase. Retried requests return the same order.
    db.rollback()
    try:
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        previous = db.execute(select(OrderRevision).where(
            OrderRevision.company_id == company_id, OrderRevision.request_key == request_key,
        )).scalar_one_or_none()
        if previous:
            if previous.source_order_id != source_id:
                raise RevisionConflictError("Revision request was already used for another order")
            result = db.get(Order, previous.revision_order_id)
            db.commit()
            return result
        source = db.get(Order, source_id)
        if source is None or source.company_id != company_id:
            raise LookupError("Order not found in this company")
        if source.status not in {"approved", "exported"}:
            raise RevisionConflictError("Only approved or exported orders can create a new revision")
        snapshot = source.approved_snapshot
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("lines"), list) or not snapshot["lines"]:
            raise RevisionConflictError("Approved snapshot is unavailable; cannot safely create a revision")
        source_lines = {line.id: line for line in source.lines}
        business = effective_business_settings(db, company_id)
        profiles = list(db.scalars(select(ExportProfile).where(ExportProfile.company_id == company_id)))
        result = Order(
            company_id=company_id, customer_id=source.customer_id,
            order_source_id=source.order_source_id, raw_input=source.raw_input,
            order_number=f"{source.order_number[:70]}-REV-{uuid.uuid4().hex[:10].upper()}",
            status="pending_review", overall_confidence=source.overall_confidence,
        )
        db.add(result)
        db.flush()
        for frozen in snapshot["lines"]:
            if not isinstance(frozen, dict):
                raise RevisionConflictError("Approved snapshot contains an invalid line")
            original = source_lines.get(frozen.get("line_id"))
            if original is None:
                raise RevisionConflictError("Approved snapshot no longer matches source lines")
            product_id = frozen.get("product_id", original.matched_product_id)
            product = db.get(Product, product_id) if product_id is not None else None
            valid_product = product is not None and product.company_id == company_id and product.active
            unit = frozen["unit"]
            compatible, package_id, _ = resolve_product_packaging(product, unit, frozen["product_phrase"]) if valid_product else (False, None, "")
            line = OrderLine(
                company_id=company_id, order_id=result.id, line_number=frozen["line_number"],
                original_text=frozen["original_text"], product_phrase=frozen["product_phrase"],
                requested_quantity=frozen["requested_quantity"], requested_unit=frozen["requested_unit"],
                raw_unit=original.raw_unit, unit_explicit=original.unit_explicit,
                quantity_text=frozen.get("quantity_text"),
                bonus_quantity=frozen.get("requested_bonus_quantity", original.bonus_quantity),
                matched_product_id=product.id if valid_product else None,
                matched_packaging_id=package_id if compatible else None,
                final_sku=product.sku if valid_product else None,
                final_quantity=frozen["quantity"], final_unit=unit,
                confidence_score=frozen.get("confidence_score", 0),
                confidence_reasons=["New revision: review against current company rules and catalog"],
                status="needs_review" if valid_product else "unresolved",
            )
            # Recalculate current promotions; old calculated bonuses/overrides
            # are not treated as customer evidence in a new rule evaluation.
            OrderWorkflowService._refresh_promotion(db, result, line)
            if _unchanged_approved_line(db, line, frozen, snapshot, business, profiles, original.matched_product_id):
                line.status = "confirmed"
                line.confidence_reasons = ["Prior approval retained: product and business quantities unchanged"]
            db.add(line)
        db.add(OrderRevision(revision_order_id=result.id, source_order_id=source.id,
                             company_id=company_id, request_key=request_key))
        db.commit()
        db.refresh(result)
        return result
    except (KeyError, TypeError) as exc:
        db.rollback()
        raise RevisionConflictError("Approved snapshot is incomplete; cannot safely create a revision") from exc
    except Exception:
        db.rollback()
        raise
