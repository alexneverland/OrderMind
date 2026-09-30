import logging
import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, List, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response, Header, File, UploadFile
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func, or_, exists
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError

from backend.app.config import settings
from backend.app.core.database import get_db
from backend.app.core.text_normalizer import (
    normalize_text, is_quantity_grounded_in_span, is_unit_grounded_in_span,
)
from backend.app.models.order import Order, OrderLine
from backend.app.models.export import ExportProfile
from backend.app.models.memory import CustomerProductAlias
from backend.app.schemas.order import OrderParseRequest, OrderParseResponse, NormalizedOrderLine
from backend.app.schemas.matching import (
    OrderMatchRequest,
    OrderMatchResponse,
    LineMatchResult,
    MatchDecision,
    ConfirmMatchRequest,
    ConfirmMatchResponse,
    CorrectMatchRequest,
    CorrectMatchResponse,
)
from backend.app.schemas.workflow import (
    CreateOrderFromMatchRequest,
    OrderResponse,
    OrderLineResponse,
    OrderApprovalResponse,
    OrderLineUpdateValuesRequest,
    OrderListItem,
)
from backend.app.services.order_parsing_service import OrderParsingService
from backend.app.services.matching_engine import MatchingEngine
from backend.app.services.learning_memory_service import LearningMemoryService, AliasConflictError, ConcurrentAliasError
from backend.app.services.order_workflow_service import (
    OrderWorkflowService,
    OrderApprovalError,
)
from backend.app.services.export_engine import (
    ExportEngine,
    OrderExportError,
    convert_order_sheet_quantities,
    profile_policy_for_order,
    business_policy_for_order,
)
from backend.app.services.order_file_service import extract_order_file, OrderFileError
from backend.app.services.business_settings_service import effective_business_settings, validate_order_quantity_policy
from backend.app.services.company_rule_service import effective_bonus

logger = logging.getLogger("ordermind.orders_api")
router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("/file-preview")
async def preview_order_file(file: UploadFile = File(...)):
    """Extract editable order text. The original binary is not retained."""
    content = await file.read(settings.MAX_ORDER_UPLOAD_SIZE_BYTES + 1)
    if len(content) > settings.MAX_ORDER_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Order file exceeds the 10 MB limit")
    try:
        extracted, method = await extract_order_file(file.filename or "", content)
    except OrderFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"filename": file.filename, "text": extracted, "method": method}


@router.get("/summary")
def order_dashboard_summary(
    day_start: datetime = Query(..., description="Operator-local day start as an ISO timestamp with offset"),
    day_end: datetime = Query(..., description="Next operator-local day start as an ISO timestamp with offset"),
    company_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    if day_start.tzinfo is None or day_end.tzinfo is None or day_end <= day_start:
        raise HTTPException(status_code=400, detail="A valid timezone-aware day range is required")
    start = day_start.astimezone(timezone.utc).replace(tzinfo=None)
    end = day_end.astimezone(timezone.utc).replace(tzinfo=None)

    def count(*conditions):
        stmt = select(func.count(Order.id)).where(*conditions)
        if company_id is not None:
            stmt = stmt.where(Order.company_id == company_id)
        return db.scalar(stmt) or 0

    pending = count(Order.status == "pending_review")
    return {
        "pending_review": pending,
        "approved_today": count(Order.approved_at >= start, Order.approved_at < end),
        "exported_today": count(Order.exported_at >= start, Order.exported_at < end),
        "needs_attention": count(
            Order.status == "pending_review",
            exists(select(OrderLine.id).where(
                OrderLine.order_id == Order.id,
                OrderLine.status.in_(("needs_review", "unresolved")),
            )),
        ),
    }


@router.get("", response_model=List[OrderListItem])
def list_orders_endpoint(
    company_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Newest orders for the operator inbox, with tenant-scoped search."""
    from backend.app.models.customer import Customer

    line_counts = select(OrderLine.order_id, func.count(OrderLine.id).label("line_count")).group_by(OrderLine.order_id).subquery()
    stmt = (select(Order, line_counts.c.line_count)
            .join(Customer, (Order.customer_id == Customer.id) & (Order.company_id == Customer.company_id))
            .outerjoin(line_counts, line_counts.c.order_id == Order.id)
            .options(selectinload(Order.customer))
            .order_by(Order.created_at.desc(), Order.id.desc())
            .limit(limit).offset(offset))
    if company_id is not None:
        stmt = stmt.where(Order.company_id == company_id)
    if status_filter:
        if status_filter not in {"pending_review", "approved", "exported", "cancelled"}:
            raise HTTPException(status_code=400, detail="Unsupported order status filter")
        stmt = stmt.where(Order.status == status_filter)
    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.where(or_(Order.order_number.ilike(term), Customer.customer_name.ilike(term), Customer.customer_code.ilike(term)))
    return [{
        "id": order.id, "company_id": order.company_id,
        "customer_id": order.customer_id, "customer": order.customer,
        "order_number": order.order_number, "status": order.status,
        "overall_confidence": order.overall_confidence,
        "created_at": order.created_at, "approved_at": order.approved_at,
        "exported_at": order.exported_at,
        "last_export_profile_id": order.last_export_profile_id,
        "line_count": count or 0,
    } for order, count in db.execute(stmt).all()]


@router.post("/parse", response_model=OrderParseResponse, status_code=status.HTTP_200_OK)
async def parse_order_endpoint(
    payload: OrderParseRequest,
    db: Session = Depends(get_db)
):
    """
    Parses unstructured order input into normalized order lines without product matching.
    """
    service = OrderParsingService()
    try:
        if len(payload.text) > settings.MAX_RAW_ORDER_TEXT_SIZE:
            raise HTTPException(status_code=413, detail="Order text exceeds maximum allowed size")
        normalized_order = await service.parse_order(
            db=db,
            company_id=payload.company_id,
            customer_id=payload.customer_id,
            text=payload.text,
            source_type=payload.source_type
        )
        if len(normalized_order.items) > settings.MAX_ORDER_LINES:
            raise HTTPException(status_code=413, detail="Order line limit exceeded")
        return OrderParseResponse(
            company_id=normalized_order.company_id,
            customer_id=normalized_order.customer_id,
            source_type=normalized_order.source_type,
            raw_input=normalized_order.raw_input,
            items=normalized_order.items,
            total_items=len(normalized_order.items)
        )
    except HTTPException:
        raise
    except (ValueError, NotImplementedError) as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except OperationalError:
        raise
    except Exception as e:
        logger.error("Unexpected server error during order parsing: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while processing the order. Please try again later."
        )


@router.post("/match", response_model=OrderMatchResponse, status_code=status.HTTP_200_OK)
async def match_order_endpoint(
    payload: OrderMatchRequest,
    db: Session = Depends(get_db)
):
    """
    Processes order input and runs deterministic matching engine with explainable confidence scoring.
    Accepts either raw text to parse & match, or pre-parsed items.
    """
    try:
        raw_input = payload.text or ""
        if len(raw_input) > settings.MAX_RAW_ORDER_TEXT_SIZE:
            raise HTTPException(status_code=413, detail="Order text exceeds maximum allowed size")
        lines_to_process = []

        if payload.items and len(payload.items) > 0:
            lines_to_process = payload.items
            if not raw_input:
                raw_input = "\n".join(it.original_text for it in payload.items)
        elif payload.text and payload.text.strip():
            service = OrderParsingService()
            normalized_order = await service.parse_order(
                db=db,
                company_id=payload.company_id,
                customer_id=payload.customer_id,
                text=payload.text,
                source_type=payload.source_type
            )
            lines_to_process = normalized_order.items
            raw_input = normalized_order.raw_input
        else:
            raise ValueError("Either 'text' or non-empty 'items' must be provided for order matching")

        if len(lines_to_process) > settings.MAX_ORDER_LINES:
            raise HTTPException(status_code=413, detail="Order line limit exceeded")
        for item in lines_to_process:
            validate_order_quantity_policy(effective_business_settings(db, payload.company_id), item.quantity_text, item.bonus_quantity)
            if normalize_text(item.original_text) not in normalize_text(raw_input):
                raise ValueError(f"Line {item.line_number} is not present in raw order text")
            if not is_quantity_grounded_in_span(item.quantity, item.original_text, raw_input, item.product_phrase, item.quantity_text, item.bonus_quantity) or not is_unit_grounded_in_span(item.unit, item.raw_unit, item.unit_explicit, item.original_text, raw_input, item.product_phrase, item.quantity_text):
                raise ValueError(f"Line {item.line_number} quantity or unit is not grounded in raw order text")

        matched_lines: List[LineMatchResult] = []
        auto_accepted_count = 0
        needs_review_count = 0
        unresolved_count = 0

        for line in lines_to_process:
            res = MatchingEngine.match_line(
                db=db,
                company_id=payload.company_id,
                customer_id=payload.customer_id,
                line_number=line.line_number,
                original_text=line.original_text,
                product_phrase=line.product_phrase,
                quantity=line.quantity,
                unit=line.unit,
                raw_unit=line.raw_unit,
                unit_explicit=line.unit_explicit
            )
            res.quantity_text = line.quantity_text
            res.bonus_quantity = line.bonus_quantity
            if res.confidence.decision == MatchDecision.AUTO_ACCEPT:
                auto_accepted_count += 1
            elif res.confidence.decision == MatchDecision.NEEDS_REVIEW:
                needs_review_count += 1
            else:
                unresolved_count += 1

            matched_lines.append(res)

        return OrderMatchResponse(
            company_id=payload.company_id,
            customer_id=payload.customer_id,
            raw_input=raw_input,
            lines=matched_lines,
            total_lines=len(matched_lines),
            auto_accepted_count=auto_accepted_count,
            needs_review_count=needs_review_count,
            unresolved_count=unresolved_count
        )
    except HTTPException:
        raise
    except (ValueError, NotImplementedError) as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except OperationalError:
        raise
    except Exception as e:
        logger.error("Unexpected server error during order matching: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while processing matching. Please try again later."
        )


@router.post("/create-from-match", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order_from_match_endpoint(
    payload: CreateOrderFromMatchRequest,
    idempotency_key_header: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db)
):
    """
    Persists matched lines into a real Order record with line records.
    Server strictly owns match computation and scoring: client-supplied candidate matches
    and decisions are ignored and recomputed server-side.
    """
    try:
        eff_idempotency_key = idempotency_key_header or payload.idempotency_key
        if eff_idempotency_key:
            eff_idempotency_key = eff_idempotency_key.strip()
            if not eff_idempotency_key or len(eff_idempotency_key) > 100:
                raise HTTPException(status_code=400, detail="Idempotency-Key must contain 1 to 100 characters")
        request_fingerprint = hashlib.sha256(json.dumps(
            payload.model_dump(mode="json", exclude={"idempotency_key"}, exclude_none=True),
            ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest() if eff_idempotency_key else None

        def existing_for_key() -> Optional[Order]:
            if not eff_idempotency_key:
                return None
            return db.execute(select(Order).where(
                Order.company_id == payload.company_id,
                Order.idempotency_key == eff_idempotency_key
            )).scalars().first()

        existing_order = existing_for_key()
        if existing_order:
            if existing_order.idempotency_fingerprint != request_fingerprint:
                raise HTTPException(status_code=409, detail="Idempotency-Key was already used with a different request")
            return existing_order

        raw_input = payload.raw_input or payload.text or ""
        if len(raw_input) > settings.MAX_RAW_ORDER_TEXT_SIZE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Order text exceeds maximum allowed size of {settings.MAX_RAW_ORDER_TEXT_SIZE} characters."
            )

        raw_items = payload.lines or payload.items
        extracted_lines = []

        if raw_items:
            if len(raw_items) > settings.MAX_ORDER_LINES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Order lines exceed maximum limit of {settings.MAX_ORDER_LINES} lines."
                )

            if not raw_input.strip():
                raise ValueError("Raw order text is required when supplying extracted items")

            seen_line_numbers = set()
            for idx, it in enumerate(raw_items):
                if isinstance(it, dict):
                    line_no = it.get("line_number", idx + 1)
                    orig_text = it.get("original_text", "")
                    phrase = it.get("product_phrase", orig_text)
                    qty = it.get("quantity") if it.get("quantity") is not None else (it.get("requested_quantity") or 1.0)
                    unit = it.get("unit") if it.get("unit") is not None else (it.get("requested_unit") or "unknown")
                    raw_unit = it.get("raw_unit")
                    unit_explicit = it.get("unit_explicit", False)
                    quantity_text = it.get("quantity_text")
                    bonus_quantity = it.get("bonus_quantity", 0)
                else:
                    line_no = getattr(it, "line_number", idx + 1)
                    orig_text = getattr(it, "original_text", "")
                    phrase = getattr(it, "product_phrase", orig_text)
                    qty = getattr(it, "quantity", None)
                    if qty is None:
                        qty = getattr(it, "requested_quantity", 1.0)
                    unit = getattr(it, "unit", None)
                    if unit is None:
                        unit = getattr(it, "requested_unit", "unknown")
                    raw_unit = getattr(it, "raw_unit", None)
                    unit_explicit = getattr(it, "unit_explicit", False)
                    quantity_text = getattr(it, "quantity_text", None)
                    bonus_quantity = getattr(it, "bonus_quantity", 0)

                item = NormalizedOrderLine.model_validate({
                    "line_number": line_no, "original_text": orig_text,
                    "product_phrase": phrase, "quantity": qty, "unit": unit,
                    "raw_unit": raw_unit, "unit_explicit": unit_explicit,
                    "quantity_text": quantity_text, "bonus_quantity": bonus_quantity,
                })
                if item.line_number in seen_line_numbers:
                    raise ValueError(f"Duplicate line number {item.line_number}")
                seen_line_numbers.add(item.line_number)
                if not normalize_text(item.original_text) or normalize_text(item.original_text) not in normalize_text(raw_input):
                    raise ValueError(f"Line {item.line_number} is not present in raw order text")
                if normalize_text(item.product_phrase) not in normalize_text(item.original_text):
                    raise ValueError(f"Line {item.line_number} product phrase is not grounded in its order item")
                validate_order_quantity_policy(effective_business_settings(db, payload.company_id), item.quantity_text, item.bonus_quantity)
                if not is_quantity_grounded_in_span(
                    item.quantity, item.original_text, raw_input, item.product_phrase,
                    item.quantity_text, item.bonus_quantity,
                ) or not is_unit_grounded_in_span(
                    item.unit, item.raw_unit, item.unit_explicit,
                    item.original_text, raw_input, item.product_phrase, item.quantity_text,
                ):
                    raise ValueError(f"Line {item.line_number} quantity or unit is not grounded in raw order text")

                # Server-owned re-matching.
                matched_line = MatchingEngine.match_line(
                    db=db,
                    company_id=payload.company_id,
                    customer_id=payload.customer_id,
                    line_number=item.line_number,
                    original_text=item.original_text,
                    product_phrase=item.product_phrase,
                    quantity=item.quantity,
                    unit=item.unit,
                    raw_unit=item.raw_unit,
                    unit_explicit=item.unit_explicit
                )
                matched_line.quantity_text = item.quantity_text
                matched_line.bonus_quantity = item.bonus_quantity
                extracted_lines.append(matched_line)
        else:
            if not payload.text or not payload.text.strip():
                raise ValueError("Either 'lines', 'items', or non-empty 'text' must be provided to create an order.")
            parser = OrderParsingService()
            parsed = await parser.parse_order(
                db=db,
                company_id=payload.company_id,
                customer_id=payload.customer_id,
                text=payload.text,
                source_type=payload.source_type
            )
            raw_input = parsed.raw_input
            if len(parsed.items) > settings.MAX_ORDER_LINES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Order lines exceed maximum limit of {settings.MAX_ORDER_LINES} lines."
                )

            for item in parsed.items:
                res = MatchingEngine.match_line(
                    db=db,
                    company_id=payload.company_id,
                    customer_id=payload.customer_id,
                    line_number=item.line_number,
                    original_text=item.original_text,
                    product_phrase=item.product_phrase,
                    quantity=item.quantity,
                    unit=item.unit,
                    raw_unit=item.raw_unit,
                    unit_explicit=item.unit_explicit
                )
                res.quantity_text = item.quantity_text
                res.bonus_quantity = item.bonus_quantity
                extracted_lines.append(res)

        try:
            order = OrderWorkflowService.create_order_from_match(
                db=db, company_id=payload.company_id, customer_id=payload.customer_id,
                raw_input=raw_input, lines=extracted_lines,
                order_number=payload.order_number,
                idempotency_key=eff_idempotency_key,
                idempotency_fingerprint=request_fingerprint,
            )
        except IntegrityError:
            db.rollback()
            existing_order = existing_for_key()
            if existing_order:
                if existing_order.idempotency_fingerprint != request_fingerprint:
                    raise HTTPException(status_code=409, detail="Idempotency-Key was already used with a different request")
                return existing_order
            raise HTTPException(status_code=409, detail="Order number or other unique order identity already exists")
        return order
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except OperationalError:
        raise
    except RuntimeError:
        raise HTTPException(status_code=503, detail="AI provider is temporarily unavailable; retry shortly")
    except Exception as e:
        logger.error("Unexpected server error during order creation: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while creating order."
        )


@router.get("/{order_id}", response_model=OrderResponse, status_code=status.HTTP_200_OK)
def get_order_endpoint(
    order_id: int,
    profile_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Retrieves an order and its line items with current lifecycle and review statuses."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id {order_id} not found"
        )
    response = OrderResponse.model_validate(order)
    if order.status in ("approved", "exported") and isinstance(order.approved_snapshot, dict):
        response.pallet_profile_ids = [
            int(profile_id)
            for profile_id, policy in order.approved_snapshot.get("export_profiles", {}).items()
            if policy.get("format") == "order_sheet" and (policy.get("palletization") or {}).get("enabled")
        ]
    if profile_id is None:
        return response
    profile = db.get(ExportProfile, profile_id)
    if not profile or profile.company_id != order.company_id or profile.format != "order_sheet":
        raise HTTPException(status_code=404, detail="Order sheet profile not found for this company")
    profile_policy = profile_policy_for_order(order, profile)
    business_policy = business_policy_for_order(db, order)
    snapshot_lines = {}
    if order.status in ("approved", "exported") and isinstance(order.approved_snapshot, dict):
        snapshot_lines = {
            item.get("line_number"): item
            for item in order.approved_snapshot.get("lines", [])
        }
    live_lines = {line.id: line for line in order.lines}
    for dto in response.lines:
        line = live_lines[dto.id]
        if order.status in ("approved", "exported"):
            item = snapshot_lines.get(line.line_number)
            if item is None or item.get("line_id", line.id) != line.id:
                dto.order_sheet_conversion_error = "Approved snapshot is unavailable or inconsistent"
                continue
            quantity = item.get("quantity")
            bonus = item.get("bonus_quantity") or 0
            unit = item.get("unit")
            ratio = item.get("pieces_per_case")
        else:
            quantity = line.final_quantity if line.final_quantity is not None else line.requested_quantity
            bonus = effective_bonus(line)
            unit = line.final_unit or line.requested_unit
            ratio = line.matched_packaging.pieces_per_case if line.matched_packaging else None
        try:
            paid, gift, output_unit = convert_order_sheet_quantities(
                quantity, bonus, unit, ratio,
                profile_policy["quantity_output_unit"],
                profile_policy["convert_case_using_pieces_per_case"],
                business_policy["allow_packaging_conversion"],
            )
            if gift and not profile_policy["bonus_separate_row"]:
                raise OrderExportError("Profile does not define how to export bonus goods")
            dto.order_sheet_paid_quantity = paid
            dto.order_sheet_bonus_quantity = gift
            dto.order_sheet_unit = output_unit
            dto.order_sheet_bonus_marker = profile_policy["bonus_marker"] if gift else None
        except (OrderExportError, TypeError, ValueError) as exc:
            dto.order_sheet_conversion_error = str(exc)
    return response


@router.post("/{order_id}/approve", response_model=OrderApprovalResponse, status_code=status.HTTP_200_OK)
def approve_order_endpoint(
    order_id: int,
    db: Session = Depends(get_db)
):
    """
    Operator approves an order.
    Enforces that NO lines remain in needs_review or unresolved status.
    Transitions order to 'approved'.
    """
    try:
        order = OrderWorkflowService.approve_order(db=db, order_id=order_id)
        total_lines = len(order.lines)
        approved_lines = sum(1 for l in order.lines if l.status in ("auto_accepted", "confirmed", "corrected"))
        pending_review_lines = sum(1 for l in order.lines if l.status == "needs_review")
        unresolved_lines = sum(1 for l in order.lines if l.status == "unresolved")

        return OrderApprovalResponse(
            order_id=order.id,
            status=order.status,
            total_lines=total_lines,
            approved_lines=approved_lines,
            pending_review_lines=pending_review_lines,
            unresolved_lines=unresolved_lines
        )
    except StaleDataError:
        raise HTTPException(status_code=409, detail="Order was changed concurrently; reload and retry")
    except OrderApprovalError as oae:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(oae)
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(ve)
        )


@router.patch("/{order_id}/lines/{line_id}", response_model=OrderLineResponse, status_code=status.HTTP_200_OK)
def update_line_final_values_endpoint(
    order_id: int,
    line_id: int,
    payload: OrderLineUpdateValuesRequest,
    db: Session = Depends(get_db)
):
    """
    Operator modifies final quantity or unit before approval
    without altering requested values. Product mutation must use the correct_line endpoint.
    """
    try:
        line = OrderWorkflowService.update_line_final_values(
            db=db,
            order_id=order_id,
            line_id=line_id,
            final_quantity=payload.final_quantity,
            final_unit=payload.final_unit,
            final_bonus_quantity=payload.final_bonus_quantity,
        )
        return line
    except StaleDataError:
        raise HTTPException(status_code=409, detail="Order was changed concurrently; reload and retry")
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )


@router.post("/lines/confirm", response_model=ConfirmMatchResponse, status_code=status.HTTP_200_OK)
@router.post("/{order_id}/lines/{line_id}/confirm", response_model=ConfirmMatchResponse, status_code=status.HTTP_200_OK)
def confirm_line_match_endpoint(
    payload: ConfirmMatchRequest,
    order_id: Optional[int] = None,
    line_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Operator confirms a product match for a customer phrase.
    Updates or creates CustomerProductAlias with incremented confirmed_count in SQL,
    and updates line status in the order if order_id and line_id exist.
    Derives customer_id, product_id, and phrase from order and line records.
    """
    eff_order_id = order_id or payload.order_id
    eff_line_id = line_id or payload.line_id
    try:
        if eff_order_id is not None and eff_line_id is not None:
            order = db.get(Order, eff_order_id)
            line = db.get(OrderLine, eff_line_id)

            if order and line:
                if line.order_id != eff_order_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Order line {eff_line_id} does not belong to order {eff_order_id}")

                # Verify client payload does not contradict path or DB identity
                if payload.customer_id is not None and payload.customer_id != order.customer_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="customer_id in payload does not match order's customer")
                if payload.order_id is not None and payload.order_id != eff_order_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="order_id in payload does not match path")
                if payload.line_id is not None and payload.line_id != eff_line_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="line_id in payload does not match path")
                if line.matched_product_id is None:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order line has no matched product. Use correct_line to assign a product first.")
                if payload.product_id is not None and payload.product_id != line.matched_product_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="product_id in payload does not match line's matched product")

                confirmed_line = OrderWorkflowService.confirm_line(
                    db=db,
                    order_id=eff_order_id,
                    line_id=eff_line_id
                )
                stmt = select(CustomerProductAlias).where(
                    CustomerProductAlias.customer_id == order.customer_id,
                    CustomerProductAlias.product_id == confirmed_line.matched_product_id,
                    CustomerProductAlias.normalized_phrase == normalize_text(confirmed_line.product_phrase)
                )
                alias = db.execute(stmt).scalars().first()
                if not alias:
                    stmt_fallback = select(CustomerProductAlias).where(
                        CustomerProductAlias.customer_id == order.customer_id,
                        CustomerProductAlias.product_id == confirmed_line.matched_product_id
                    )
                    alias = db.execute(stmt_fallback).scalars().first()

                return ConfirmMatchResponse(
                    status="confirmed",
                    customer_id=alias.customer_id if alias else order.customer_id,
                    product_id=alias.product_id if alias else confirmed_line.matched_product_id,
                    original_phrase=alias.original_phrase if alias else confirmed_line.product_phrase,
                    confirmed_count=alias.confirmed_count if alias else 1,
                    corrected_count=alias.corrected_count if alias else 0
                )
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Order {eff_order_id} or line {eff_line_id} does not exist or does not belong to order")

        if (eff_order_id is None) != (eff_line_id is None):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="order_id and line_id must be supplied together")

        alias = LearningMemoryService.confirm_match(
            db=db,
            customer_id=payload.customer_id,
            product_id=payload.product_id,
            original_phrase=payload.original_phrase,
            order_id=eff_order_id,
            line_id=eff_line_id
        )
        db.commit()
        db.refresh(alias)
        return ConfirmMatchResponse(
            status="confirmed",
            customer_id=alias.customer_id,
            product_id=alias.product_id,
            original_phrase=alias.original_phrase,
            confirmed_count=alias.confirmed_count,
            corrected_count=alias.corrected_count
        )
    except HTTPException:
        raise
    except (StaleDataError, IntegrityError):
        db.rollback()
        raise HTTPException(status_code=409, detail="Order or alias was changed concurrently; reload and retry")
    except ConcurrentAliasError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Customer alias changed concurrently; reload and retry")
    except (AliasConflictError, ValueError) as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except OperationalError:
        raise
    except Exception as e:
        logger.error("Unexpected server error during match confirmation: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while confirming match."
        )


@router.post("/lines/correct", response_model=CorrectMatchResponse, status_code=status.HTTP_200_OK)
@router.post("/{order_id}/lines/{line_id}/correct", response_model=CorrectMatchResponse, status_code=status.HTTP_200_OK)
def correct_line_match_endpoint(
    payload: CorrectMatchRequest,
    order_id: Optional[int] = None,
    line_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """
    Operator overrides/corrects a suggested product to the real product.
    Atomically creates a HumanCorrection record and updates CustomerProductAlias,
    and updates line status in the order if order_id and line_id exist.
    """
    eff_order_id = order_id or payload.order_id
    eff_line_id = line_id or payload.line_id
    try:
        if eff_order_id is not None and eff_line_id is not None:
            order = db.get(Order, eff_order_id)
            line = db.get(OrderLine, eff_line_id)

            if order and line:
                if line.order_id != eff_order_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Order line {eff_line_id} does not belong to order {eff_order_id}")

                # Verify client payload does not contradict path or DB identity
                if payload.customer_id is not None and payload.customer_id != order.customer_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="customer_id in payload does not match order's customer")
                if payload.order_id is not None and payload.order_id != eff_order_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="order_id in payload does not match path")
                if payload.line_id is not None and payload.line_id != eff_line_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="line_id in payload does not match path")
                if payload.suggested_product_id is not None and line.matched_product_id is not None and payload.suggested_product_id != line.matched_product_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="suggested_product_id in payload does not match line's current matched product")

                correction, corrected_line = OrderWorkflowService.correct_line(
                    db=db,
                    order_id=eff_order_id,
                    line_id=eff_line_id,
                    correct_product_id=payload.correct_product_id,
                    notes=payload.notes
                )
                stmt = select(CustomerProductAlias).where(
                    CustomerProductAlias.customer_id == order.customer_id,
                    CustomerProductAlias.product_id == payload.correct_product_id,
                    CustomerProductAlias.normalized_phrase == normalize_text(corrected_line.product_phrase)
                )
                alias = db.execute(stmt).scalars().first()
                if not alias:
                    stmt_fallback = select(CustomerProductAlias).where(
                        CustomerProductAlias.customer_id == order.customer_id,
                        CustomerProductAlias.product_id == payload.correct_product_id
                    )
                    alias = db.execute(stmt_fallback).scalars().first()

                return CorrectMatchResponse(
                    status="corrected",
                    correction_id=correction.id,
                    customer_id=alias.customer_id if alias else order.customer_id,
                    suggested_product_id=correction.suggested_product_id,
                    correct_product_id=corrected_line.matched_product_id,
                    original_phrase=alias.original_phrase if alias else corrected_line.product_phrase,
                    confirmed_count=alias.confirmed_count if alias else 1,
                    corrected_count=alias.corrected_count if alias else 1,
                    order_id=correction.order_id,
                    order_line_id=correction.order_line_id
                )
            else:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Order {eff_order_id} or line {eff_line_id} does not exist or does not belong to order")

        if (eff_order_id is None) != (eff_line_id is None):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="order_id and line_id must be supplied together")

        correction, alias = LearningMemoryService.correct_match(
            db=db,
            customer_id=payload.customer_id,
            correct_product_id=payload.correct_product_id,
            original_phrase=payload.original_phrase,
            suggested_product_id=payload.suggested_product_id,
            order_id=eff_order_id,
            line_id=eff_line_id,
            notes=payload.notes
        )
        db.commit()
        db.refresh(correction)
        db.refresh(alias)
        return CorrectMatchResponse(
            status="corrected",
            correction_id=correction.id,
            customer_id=alias.customer_id,
            suggested_product_id=correction.suggested_product_id,
            correct_product_id=alias.product_id,
            original_phrase=alias.original_phrase,
            confirmed_count=alias.confirmed_count,
            corrected_count=alias.corrected_count,
            order_id=correction.order_id,
            order_line_id=correction.order_line_id
        )
    except HTTPException:
        raise
    except (StaleDataError, IntegrityError):
        db.rollback()
        raise HTTPException(status_code=409, detail="Order or alias was changed concurrently; reload and retry")
    except ConcurrentAliasError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Customer alias changed concurrently; reload and retry")
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except OperationalError:
        raise
    except Exception as e:
        logger.error("Unexpected server error during match correction: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while correcting match."
        )


@router.get("/{order_id}/pallet-preview/{profile_id}")
def preview_pallets(order_id: int, profile_id: int, db: Session = Depends(get_db)):
    from backend.app.services.pallet_planner import plan_for_order
    order = db.get(Order, order_id)
    profile = db.get(ExportProfile, profile_id)
    if not order or not profile or profile.company_id != order.company_id or profile.format != "order_sheet":
        raise HTTPException(status_code=404, detail="Order-sheet profile not found for this order")
    try:
        plan, _ = plan_for_order(db, order, profile)
        for pallet in plan["pallets"]:
            for item in pallet["items"]:
                item.pop("rows", None)
        return plan
    except (OrderExportError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{order_id}/export/{profile_id}")
def export_order_endpoint(
    order_id: int,
    profile_id: int,
    preview: bool = Query(False, description="Preview export without marking order as exported"),
    db: Session = Depends(get_db)
):
    """
    Renders approved order into configured format (XLSX, CSV, JSON).
    Blocks unapproved orders unless preview is True.
    """
    try:
        content, media_type, filename = ExportEngine.export_order(
            db=db,
            order_id=order_id,
            profile_id=profile_id,
            preview=preview
        )
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    except StaleDataError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Order was changed concurrently; reload and retry")
    except OrderExportError as oee:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(oee)
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except OperationalError:
        raise
    except Exception as e:
        logger.error("Unexpected server error during order export: %s", type(e).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while exporting the order."
        )
