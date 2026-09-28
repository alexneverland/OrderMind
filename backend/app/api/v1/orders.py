import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
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
from backend.app.services.order_parsing_service import OrderParsingService
from backend.app.services.matching_engine import MatchingEngine
from backend.app.services.learning_memory_service import LearningMemoryService, AliasConflictError


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
    Updates or creates CustomerProductAlias with incremented confirmed_count in SQL.
    """
    eff_order_id = order_id or payload.order_id
    eff_line_id = line_id or payload.line_id
    try:
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
    Atomically creates a HumanCorrection record and updates CustomerProductAlias.
    """
    eff_order_id = order_id or payload.order_id
    eff_line_id = line_id or payload.line_id
    try:
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
            corrected_count=alias.corrected_count
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
