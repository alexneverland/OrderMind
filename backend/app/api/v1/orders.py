import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Query, Response
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.core.database import get_db
from backend.app.models.order import Order
from backend.app.models.memory import CustomerProductAlias
from backend.app.schemas.order import OrderParseRequest, OrderParseResponse
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
)
from backend.app.services.order_parsing_service import OrderParsingService
from backend.app.services.matching_engine import MatchingEngine
from backend.app.services.learning_memory_service import LearningMemoryService, AliasConflictError
from backend.app.services.order_workflow_service import (
    OrderWorkflowService,
    OrderApprovalError,
)
from backend.app.services.export_engine import (
    ExportEngine,
    OrderExportError,
)

logger = logging.getLogger("ordermind.orders_api")
router = APIRouter(prefix="/orders", tags=["Orders"])


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
        normalized_order = await service.parse_order(
            db=db,
            company_id=payload.company_id,
            customer_id=payload.customer_id,
            text=payload.text,
            source_type=payload.source_type
        )
        return OrderParseResponse(
            company_id=normalized_order.company_id,
            customer_id=normalized_order.customer_id,
            source_type=normalized_order.source_type,
            raw_input=normalized_order.raw_input,
            items=normalized_order.items,
            total_items=len(normalized_order.items)
        )
    except (ValueError, NotImplementedError) as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.exception("Unexpected server error during order parsing: %s", str(e))
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
    except (ValueError, NotImplementedError) as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.exception("Unexpected server error during order matching: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while processing matching. Please try again later."
        )


@router.post("/create-from-match", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order_from_match_endpoint(
    payload: CreateOrderFromMatchRequest,
    db: Session = Depends(get_db)
):
    """
    Persists matched lines into a real Order record with line records.
    If lines are not supplied, parses and matches the text input first.
    """
    try:
        raw_input = payload.raw_input or payload.text or ""
        lines = payload.lines

        if not lines:
            if not payload.text or not payload.text.strip():
                raise ValueError("Either 'lines' or non-empty 'text' must be provided to create an order.")
            parser = OrderParsingService()
            parsed = await parser.parse_order(
                db=db,
                company_id=payload.company_id,
                customer_id=payload.customer_id,
                text=payload.text,
                source_type=payload.source_type
            )
            raw_input = parsed.raw_input
            lines = []
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
                lines.append(res)

        order = OrderWorkflowService.create_order_from_match(
            db=db,
            company_id=payload.company_id,
            customer_id=payload.customer_id,
            raw_input=raw_input,
            lines=lines,
            order_number=payload.order_number
        )
        return order
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.exception("Unexpected server error during order creation: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while creating order."
        )


@router.get("/{order_id}", response_model=OrderResponse, status_code=status.HTTP_200_OK)
def get_order_endpoint(
    order_id: int,
    db: Session = Depends(get_db)
):
    """Retrieves an order and its line items with current lifecycle and review statuses."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Order with id {order_id} not found"
        )
    return order


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
    Operator modifies final product, quantity, or unit before approval
    without altering requested values.
    """
    try:
        line = OrderWorkflowService.update_line_final_values(
            db=db,
            order_id=order_id,
            line_id=line_id,
            final_quantity=payload.final_quantity,
            final_unit=payload.final_unit,
            final_product_id=payload.final_product_id
        )
        return line
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
    """
    eff_order_id = order_id or payload.order_id
    eff_line_id = line_id or payload.line_id
    try:
        if eff_order_id is not None and eff_line_id is not None and db.get(Order, eff_order_id):
            line = OrderWorkflowService.confirm_line(
                db=db,
                order_id=eff_order_id,
                line_id=eff_line_id
            )
            stmt = select(CustomerProductAlias).where(
                CustomerProductAlias.customer_id == payload.customer_id,
                CustomerProductAlias.product_id == (line.matched_product_id or payload.product_id)
            )
            alias = db.execute(stmt).scalars().first()
            if not alias:
                alias = LearningMemoryService.confirm_match(
                    db=db,
                    customer_id=payload.customer_id,
                    product_id=line.matched_product_id or payload.product_id,
                    original_phrase=payload.original_phrase
                )
            return ConfirmMatchResponse(
                status="confirmed",
                customer_id=alias.customer_id,
                product_id=alias.product_id,
                original_phrase=alias.original_phrase,
                confirmed_count=alias.confirmed_count,
                corrected_count=alias.corrected_count
            )

        alias = LearningMemoryService.confirm_match(
            db=db,
            customer_id=payload.customer_id,
            product_id=payload.product_id,
            original_phrase=payload.original_phrase,
            order_id=eff_order_id,
            line_id=eff_line_id
        )
        return ConfirmMatchResponse(
            status="confirmed",
            customer_id=alias.customer_id,
            product_id=alias.product_id,
            original_phrase=alias.original_phrase,
            confirmed_count=alias.confirmed_count,
            corrected_count=alias.corrected_count
        )
    except (AliasConflictError, ValueError) as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.exception("Unexpected server error during match confirmation: %s", str(e))
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
        if eff_order_id is not None and eff_line_id is not None and db.get(Order, eff_order_id):
            correction, line = OrderWorkflowService.correct_line(
                db=db,
                order_id=eff_order_id,
                line_id=eff_line_id,
                correct_product_id=payload.correct_product_id,
                notes=payload.notes
            )
            stmt = select(CustomerProductAlias).where(
                CustomerProductAlias.customer_id == payload.customer_id,
                CustomerProductAlias.product_id == payload.correct_product_id
            )
            alias = db.execute(stmt).scalars().first()
            return CorrectMatchResponse(
                status="corrected",
                correction_id=correction.id,
                customer_id=alias.customer_id if alias else payload.customer_id,
                suggested_product_id=correction.suggested_product_id,
                correct_product_id=line.matched_product_id,
                original_phrase=alias.original_phrase if alias else payload.original_phrase,
                confirmed_count=alias.confirmed_count if alias else 1,
                corrected_count=alias.corrected_count if alias else 1,
                order_id=correction.order_id,
                order_line_id=correction.order_line_id
            )

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
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.exception("Unexpected server error during match correction: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while correcting match."
        )


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
    except Exception as e:
        logger.exception("Unexpected server error during order export: %s", str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while exporting the order."
        )
