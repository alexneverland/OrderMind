from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.schemas.order import OrderParseRequest, OrderParseResponse
from backend.app.services.order_parsing_service import OrderParsingService

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
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Order parsing failed: {str(e)}"
        )
