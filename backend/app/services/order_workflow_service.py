from typing import Optional, List, Tuple
from datetime import datetime, timezone
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.models.order import Order, OrderLine, MatchCandidate
from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.memory import HumanCorrection
from backend.app.schemas.workflow import (
    OrderStatus,
    OrderLineStatus,
    CanonicalOrder,
    CanonicalOrderCustomer,
    CanonicalOrderItem,
)
from backend.app.schemas.matching import LineMatchResult, MatchDecision
from backend.app.services.learning_memory_service import LearningMemoryService
from backend.app.core.text_normalizer import normalize_unit, resolve_unit


class OrderApprovalError(ValueError):
    """Raised when an order cannot be approved due to unreviewed or unresolved lines."""
    pass


class OrderWorkflowService:
    """
    Manages order creation from match results, review states, line corrections/confirmations,
    order approvals, and canonical representations.
    """

    ALLOWED_ORDER_TRANSITIONS = {
        OrderStatus.DRAFT.value: {OrderStatus.PROCESSING.value, OrderStatus.PENDING_REVIEW.value, OrderStatus.CANCELLED.value},
        OrderStatus.PROCESSING.value: {OrderStatus.PENDING_REVIEW.value, OrderStatus.CANCELLED.value},
        OrderStatus.PENDING_REVIEW.value: {OrderStatus.APPROVED.value, OrderStatus.CANCELLED.value},
        OrderStatus.APPROVED.value: {OrderStatus.EXPORTED.value, OrderStatus.CANCELLED.value},
        OrderStatus.EXPORTED.value: set(),
        OrderStatus.CANCELLED.value: set(),
    }

    @classmethod
    def create_order_from_match(
        cls,
        db: Session,
        company_id: int,
        customer_id: int,
        raw_input: str,
        lines: List[LineMatchResult],
        order_number: Optional[str] = None,
        order_source_id: Optional[int] = None,
        idempotency_key: Optional[str] = None
    ) -> Order:
        """
        Persists matched order lines into a real Order record.
        Maintains clear distinction between requested and final values.
        """
        company = db.get(Company, company_id)
        if not company:
            raise ValueError(f"Company with id {company_id} does not exist")

        customer = db.get(Customer, customer_id)
        if not customer:
            raise ValueError(f"Customer with id {customer_id} does not exist")

        if customer.company_id != company_id:
            raise ValueError(f"Customer {customer_id} belongs to company {customer.company_id}, not {company_id}")

        if not order_number or not order_number.strip():
            now_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            rand_suffix = uuid.uuid4().hex[:6].upper()
            order_number = f"ORD-{now_str}-{rand_suffix}"

        overall_conf = 0.0
        if lines:
            overall_conf = sum(l.confidence.score for l in lines) / len(lines)

        try:
            order = Order(
                company_id=company_id,
                customer_id=customer_id,
                order_source_id=order_source_id,
                order_number=order_number.strip(),
                idempotency_key=idempotency_key.strip() if idempotency_key else None,
                status=OrderStatus.PENDING_REVIEW.value,
                overall_confidence=overall_conf,
                raw_input=raw_input.strip() if raw_input else ""
            )
            db.add(order)
            db.flush()

            for line_res in lines:
                # Determine line status based on match decision
                if line_res.confidence.decision == MatchDecision.AUTO_ACCEPT:
                    line_status = OrderLineStatus.AUTO_ACCEPTED.value
                elif line_res.confidence.decision == MatchDecision.NEEDS_REVIEW:
                    line_status = OrderLineStatus.NEEDS_REVIEW.value
                else:
                    line_status = OrderLineStatus.UNRESOLVED.value

                matched_prod_id = line_res.best_match.product_id if line_res.best_match else None
                final_sku = line_res.best_match.sku if line_res.best_match else None
                final_unit = (line_res.best_match.unit if line_res.best_match else None) or line_res.unit

                order_line = OrderLine(
                    order_id=order.id,
                    line_number=line_res.line_number,
                    original_text=line_res.original_text,
                    product_phrase=line_res.product_phrase,
                    requested_quantity=line_res.quantity,
                    requested_unit=line_res.unit,
                    raw_unit=line_res.raw_unit,
                    unit_explicit=line_res.unit_explicit,
                    matched_product_id=matched_prod_id,
                    final_sku=final_sku,
                    final_quantity=line_res.quantity,
                    final_unit=final_unit,
                    confidence_score=line_res.confidence.score,
                    confidence_reasons=line_res.confidence.reasons,
                    status=line_status
                )
                db.add(order_line)
                db.flush()

                # Persist match candidates for explainability and operator audit
                persisted_product_ids = set()

                if line_res.best_match:
                    winning_match_type = "best_match"
                    if line_res.confidence.reasons:
                        first_reason = line_res.confidence.reasons[0].lower()
                        if "sku" in first_reason:
                            winning_match_type = "exact_sku"
                        elif "barcode" in first_reason:
                            winning_match_type = "exact_barcode"
                        elif "customer" in first_reason and "alias" in first_reason:
                            winning_match_type = "customer_alias"
                        elif "global" in first_reason and "alias" in first_reason:
                            winning_match_type = "global_alias"
                        elif "exact" in first_reason:
                            winning_match_type = "exact_match"
                        elif "fuzzy" in first_reason:
                            winning_match_type = "fuzzy_match"
                        elif "ai" in first_reason or "rerank" in first_reason:
                            winning_match_type = "ai_rerank"

                    winner_expl = "; ".join(line_res.confidence.reasons) if line_res.confidence.reasons else "Best match"
                    if len(winner_expl) > 500:
                        winner_expl = winner_expl[:497] + "..."

                    winner_record = MatchCandidate(
                        order_line_id=order_line.id,
                        product_id=line_res.best_match.product_id,
                        rank=1,
                        match_type=winning_match_type,
                        score=line_res.confidence.score,
                        explanation=winner_expl
                    )
                    db.add(winner_record)
                    persisted_product_ids.add(line_res.best_match.product_id)

                for cand in line_res.alternatives:
                    if cand.product_id in persisted_product_ids:
                        continue
                    cand_rank = cand.rank if cand.rank > 1 else (2 if line_res.best_match else 1)
                    cand_match_type = cand.evidence[0].evidence_type if cand.evidence else "alternative"
                    cand_expl = "; ".join(e.detail for e in cand.evidence) if cand.evidence else ""
                    if len(cand_expl) > 500:
                        cand_expl = cand_expl[:497] + "..."

                    cand_record = MatchCandidate(
                        order_line_id=order_line.id,
                        product_id=cand.product_id,
                        rank=cand_rank,
                        match_type=cand_match_type[:50],
                        score=cand.score,
                        explanation=cand_expl
                    )
                    db.add(cand_record)
                    persisted_product_ids.add(cand.product_id)

            db.commit()
            db.refresh(order)
            return order
        except Exception:
            db.rollback()
            raise

    @classmethod
    def confirm_line(
        cls,
        db: Session,
        order_id: int,
        line_id: int,
        user_notes: Optional[str] = None
    ) -> OrderLine:
        """
        Operator confirms a suggested match for an order line:
        - Line transitions from needs_review -> confirmed.
        - Calls LearningMemoryService.confirm_match to feed the learning memory loop.
        """
        order = db.get(Order, order_id)
        if not order:
            raise ValueError(f"Order with id {order_id} does not exist")

        if order.status in (OrderStatus.APPROVED.value, OrderStatus.CANCELLED.value, OrderStatus.EXPORTED.value):
            raise ValueError(f"Order {order_id} is '{order.status}' and its lines cannot be modified")

        order_line = db.get(OrderLine, line_id)
        if not order_line:
            raise ValueError(f"Order line with id {line_id} does not exist")

        if order_line.order_id != order_id:
            raise ValueError(f"Order line {line_id} does not belong to order {order_id}")

        if order_line.matched_product_id is None:
            raise ValueError(
                f"Order line {line_id} has no matched product. Use correct_line to assign a product first."
            )

        try:
            order_line.status = OrderLineStatus.CONFIRMED.value

            # Update learning memory without committing in sub-service
            LearningMemoryService.confirm_match(
                db=db,
                customer_id=order.customer_id,
                product_id=order_line.matched_product_id,
                original_phrase=order_line.product_phrase,
                order_id=order.id,
                line_id=order_line.id,
                commit=False
            )

            db.commit()
            db.refresh(order_line)
            return order_line
        except Exception:
            db.rollback()
            raise

    @classmethod
    def correct_line(
        cls,
        db: Session,
        order_id: int,
        line_id: int,
        correct_product_id: int,
        notes: Optional[str] = None
    ) -> Tuple[HumanCorrection, OrderLine]:
        """
        Operator overrides/corrects a match for an order line:
        - Validates company isolation on product.
        - Updates line's matched product, final_sku, final_unit.
        - Line transitions to 'corrected'.
        - Records HumanCorrection and updates customer alias via LearningMemoryService.
        """
        order = db.get(Order, order_id)
        if not order:
            raise ValueError(f"Order with id {order_id} does not exist")

        if order.status in (OrderStatus.APPROVED.value, OrderStatus.CANCELLED.value, OrderStatus.EXPORTED.value):
            raise ValueError(f"Order {order_id} is '{order.status}' and its lines cannot be modified")

        order_line = db.get(OrderLine, line_id)
        if not order_line:
            raise ValueError(f"Order line with id {line_id} does not exist")

        if order_line.order_id != order_id:
            raise ValueError(f"Order line {line_id} does not belong to order {order_id}")

        correct_prod = db.get(Product, correct_product_id)
        if not correct_prod:
            raise ValueError(f"Product with id {correct_product_id} does not exist")

        if correct_prod.company_id != order.company_id:
            raise ValueError(
                f"Product {correct_product_id} belongs to company {correct_prod.company_id}, "
                f"not order company {order.company_id}"
            )

        previous_suggested_id = order_line.matched_product_id

        try:
            # Update line values
            order_line.matched_product_id = correct_product_id
            order_line.final_sku = correct_prod.sku
            order_line.final_unit = correct_prod.unit
            order_line.status = OrderLineStatus.CORRECTED.value

            # Record correction and update learning memory without committing in sub-service
            correction, _ = LearningMemoryService.correct_match(
                db=db,
                customer_id=order.customer_id,
                correct_product_id=correct_product_id,
                original_phrase=order_line.product_phrase,
                suggested_product_id=previous_suggested_id,
                order_id=order.id,
                line_id=order_line.id,
                notes=notes,
                commit=False
            )

            db.commit()
            db.refresh(order_line)
            db.refresh(correction)
            return correction, order_line
        except Exception:
            db.rollback()
            raise

    @classmethod
    def update_line_final_values(
        cls,
        db: Session,
        order_id: int,
        line_id: int,
        final_quantity: Optional[float] = None,
        final_unit: Optional[str] = None
    ) -> OrderLine:
        """
        Allows operator to adjust approved values (quantity, unit)
        without destroying original requested values.
        Product mutation is strictly prohibited here and must use correct_line().
        Validates unit compatibility against product and packagings.
        """
        order = db.get(Order, order_id)
        if not order:
            raise ValueError(f"Order with id {order_id} does not exist")

        if order.status in (OrderStatus.APPROVED.value, OrderStatus.CANCELLED.value, OrderStatus.EXPORTED.value):
            raise ValueError(f"Order {order_id} is '{order.status}' and its lines cannot be modified")

        order_line = db.get(OrderLine, line_id)
        if not order_line:
            raise ValueError(f"Order line with id {line_id} does not exist")

        if order_line.order_id != order_id:
            raise ValueError(f"Order line {line_id} does not belong to order {order_id}")

        try:
            if final_quantity is not None:
                if final_quantity <= 0:
                    raise ValueError("Quantity must be greater than zero")
                order_line.final_quantity = final_quantity

            if final_unit is not None:
                canonical_unit, raw_unit, _ = resolve_unit(final_unit)
                if canonical_unit == "unknown" or canonical_unit not in ("piece", "kg", "case", "pallet") or not final_unit.strip():
                    raise ValueError(f"Unknown or invalid unit '{final_unit}'. Supported: piece, kg, case, pallet")

                if order_line.matched_product_id:
                    prod = db.get(Product, order_line.matched_product_id)
                    if prod:
                        canonical_prod_unit = normalize_unit(prod.unit)
                        if canonical_unit == canonical_prod_unit:
                            order_line.matched_packaging_id = None
                        else:
                            matching_pkgs = [
                                pkg for pkg in prod.packagings
                                if normalize_unit(pkg.package_type) == canonical_unit or normalize_unit(pkg.unit) == canonical_unit
                            ]
                            if len(matching_pkgs) == 1:
                                order_line.matched_packaging_id = matching_pkgs[0].id
                            elif len(matching_pkgs) > 1:
                                factors = set(p.pieces_per_case for p in matching_pkgs)
                                if len(factors) > 1:
                                    raise ValueError(
                                        f"Ambiguous packaging for unit '{canonical_unit}': multiple packagings match with different quantities"
                                    )
                                order_line.matched_packaging_id = matching_pkgs[0].id

                order_line.final_unit = canonical_unit

            db.commit()
            db.refresh(order_line)
            return order_line
        except Exception:
            db.rollback()
            raise

    @classmethod
    def approve_order(cls, db: Session, order_id: int) -> Order:
        """
        Enforces approval safety rules:
        - Order cannot be approved if status is not 'pending_review' (or already approved).
        - Every line must have status in {auto_accepted, confirmed, corrected}.
        - Every line must have a valid matched product and positive quantity.
        - Transitions order status to 'approved' and records approved_snapshot for immutable export.
        """
        order = db.get(Order, order_id)
        if not order:
            raise ValueError(f"Order with id {order_id} does not exist")

        if order.status == OrderStatus.APPROVED.value:
            return order  # Idempotent approval

        if order.status != OrderStatus.PENDING_REVIEW.value:
            raise ValueError(
                f"Order {order_id} cannot be approved because its status is '{order.status}' (expected 'pending_review')"
            )

        if not order.lines:
            raise OrderApprovalError("Order has no lines and cannot be approved")

        unreviewed = [
            l for l in order.lines
            if l.status in (OrderLineStatus.NEEDS_REVIEW.value, OrderLineStatus.UNRESOLVED.value)
        ]
        if unreviewed:
            raise OrderApprovalError(
                f"Order cannot be approved because {len(unreviewed)} line(s) still require review."
            )

        allowed_line_statuses = {
            OrderLineStatus.AUTO_ACCEPTED.value,
            OrderLineStatus.CONFIRMED.value,
            OrderLineStatus.CORRECTED.value,
        }

        for line in order.lines:
            if line.status not in allowed_line_statuses:
                raise OrderApprovalError(
                    f"Order cannot be approved because line {line.line_number} is in '{line.status}' status (must be auto_accepted, confirmed, or corrected)."
                )
            if line.matched_product_id is None:
                raise OrderApprovalError(
                    f"Order line {line.line_number} has no matched product and cannot be approved."
                )
            qty = line.final_quantity if line.final_quantity is not None else line.requested_quantity
            if qty <= 0:
                raise OrderApprovalError(
                    f"Order line {line.line_number} has non-positive quantity."
                )

        try:
            now = datetime.now(timezone.utc)
            order.status = OrderStatus.APPROVED.value
            order.approved_at = now
            order.confirmed_at = now

            customer = order.customer
            order.approved_snapshot = {
                "order": {
                    "id": order.id,
                    "order_number": order.order_number,
                    "company_id": order.company_id,
                    "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S") if order.created_at else "",
                    "approved_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "overall_confidence": round(order.overall_confidence, 2)
                },
                "customer": {
                    "id": customer.id if customer else None,
                    "customer_code": customer.customer_code if customer else "",
                    "customer_name": customer.customer_name if customer else "",
                    "email": customer.email if customer else "",
                    "phone": customer.phone if customer else "",
                },
                "lines": [
                    {
                        "line_number": l.line_number,
                        "original_text": l.original_text,
                        "product_phrase": l.product_phrase,
                        "sku": l.final_sku or (l.matched_product.sku if l.matched_product else ""),
                        "description": (l.matched_product.description if l.matched_product else l.product_phrase),
                        "quantity": l.final_quantity if l.final_quantity is not None else l.requested_quantity,
                        "unit": l.final_unit or l.requested_unit,
                        "requested_quantity": l.requested_quantity,
                        "requested_unit": l.requested_unit,
                        "confidence_score": round(l.confidence_score, 2),
                        "status": l.status,
                        "barcode": l.matched_product.barcode if l.matched_product else "",
                    }
                    for l in sorted(order.lines, key=lambda x: x.line_number)
                ]
            }

            db.commit()
            db.refresh(order)
            return order
        except Exception:
            db.rollback()
            raise

    @classmethod
    def cancel_order(cls, db: Session, order_id: int) -> Order:
        """Cancels an order. Forbids cancelling exported orders."""
        order = db.get(Order, order_id)
        if not order:
            raise ValueError(f"Order with id {order_id} does not exist")

        if order.status in (OrderStatus.EXPORTED.value, OrderStatus.CANCELLED.value):
            raise ValueError(f"Order {order_id} cannot be cancelled because its status is '{order.status}'")

        try:
            order.status = OrderStatus.CANCELLED.value
            db.commit()
            db.refresh(order)
            return order
        except Exception:
            db.rollback()
            raise

    @classmethod
    def get_canonical_order(cls, order: Order) -> CanonicalOrder:
        """
        Transforms approved Order into internal canonical structured object.
        Reads from approved_snapshot if available to guarantee immutability.
        """
        if order.approved_snapshot and "lines" in order.approved_snapshot:
            snap = order.approved_snapshot
            snap_cust = snap.get("customer", {})
            snap_order = snap.get("order", {})
            return CanonicalOrder(
                order_id=order.id,
                order_number=order.order_number,
                company_id=order.company_id,
                customer=CanonicalOrderCustomer(
                    id=snap_cust.get("id") or 0,
                    customer_code=snap_cust.get("customer_code") or "",
                    customer_name=snap_cust.get("customer_name") or ""
                ),
                status=order.status,
                created_at=snap_order.get("created_at") or (order.created_at.isoformat() if order.created_at else ""),
                approved_at=snap_order.get("approved_at") or (order.approved_at.isoformat() if order.approved_at else None),
                items=[
                    CanonicalOrderItem(
                        line_number=item["line_number"],
                        sku=item["sku"],
                        description=item["description"],
                        quantity=item["quantity"],
                        unit=item["unit"],
                        barcode=item.get("barcode") or None,
                        original_text=item["original_text"],
                        requested_quantity=item["requested_quantity"],
                        requested_unit=item["requested_unit"]
                    )
                    for item in snap["lines"]
                ]
            )

        customer = order.customer
        canonical_items: List[CanonicalOrderItem] = []

        for line in sorted(order.lines, key=lambda l: l.line_number):
            prod = line.matched_product
            qty = line.final_quantity if line.final_quantity is not None else line.requested_quantity
            unit = line.final_unit or line.requested_unit
            desc = prod.description if prod else line.product_phrase
            sku = line.final_sku or (prod.sku if prod else "")

            canonical_items.append(
                CanonicalOrderItem(
                    line_number=line.line_number,
                    sku=sku,
                    description=desc,
                    quantity=qty,
                    unit=unit,
                    barcode=prod.barcode if prod else None,
                    original_text=line.original_text,
                    requested_quantity=line.requested_quantity,
                    requested_unit=line.requested_unit
                )
            )

        return CanonicalOrder(
            order_id=order.id,
            order_number=order.order_number,
            company_id=order.company_id,
            customer=CanonicalOrderCustomer(
                id=customer.id if customer else 0,
                customer_code=customer.customer_code if customer else "",
                customer_name=customer.customer_name if customer else ""
            ),
            status=order.status,
            created_at=order.created_at.isoformat() if order.created_at else "",
            approved_at=order.approved_at.isoformat() if order.approved_at else None,
            items=canonical_items
        )
