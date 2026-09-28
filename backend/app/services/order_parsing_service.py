import time
import logging
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.adapters.registry import get_input_adapter
from backend.app.ai.base import BaseAIProvider
from backend.app.ai.factory import get_ai_provider
from backend.app.schemas.order import (
    NormalizedOrder,
    NormalizedOrderLine,
    NormalizedOrderLineDraft
)
from backend.app.core.text_normalizer import normalize_unit

logger = logging.getLogger("ordermind.parsing")


class OrderParsingService:
    """
    Coordinates order intake, input normalization, AI/Mock extraction, and Pydantic validation.
    Agnostic to specific AI providers and input channels.
    """

    def __init__(self, ai_provider: Optional[BaseAIProvider] = None):
        self.ai_provider = ai_provider

    async def parse_order(
        self,
        db: Session,
        company_id: int,
        customer_id: int,
        text: str,
        source_type: str = "plain_text",
        metadata: Optional[Dict[str, Any]] = None,
        provider_override: Optional[str] = None
    ) -> NormalizedOrder:
        """
        Executes end-to-end parsing pipeline:
        Input -> Adapter -> NormalizedInput -> AI Extraction -> Validated NormalizedOrder
        """
        # 1. Verify Company exists
        company = db.get(Company, company_id)
        if not company:
            raise ValueError(f"Company with id {company_id} not found")

        # 2. Verify Customer exists and belongs to Company
        customer = db.get(Customer, customer_id)
        if not customer:
            raise ValueError(f"Customer with id {customer_id} not found")
        if customer.company_id != company_id:
            raise ValueError(f"Customer {customer_id} does not belong to Company {company_id}")

        # 3. Input Adapter normalization
        adapter = get_input_adapter(source_type)
        normalized_input = adapter.normalize(raw_input=text, metadata=metadata)

        # 4. Resolve AI Provider
        provider = self.ai_provider or get_ai_provider(provider_override)

        # 5. Extract with latency logging
        start_time = time.perf_counter()
        provider_name = getattr(provider, "name", "unknown")
        model_name = getattr(provider, "model_name", "default")

        try:
            draft_items: List[NormalizedOrderLineDraft] = await provider.extract_order(
                normalized_input=normalized_input,
                context={"company_id": company_id, "customer_id": customer_id}
            )
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # 6. Build sequential, validated lines
            order_lines: List[NormalizedOrderLine] = []
            for idx, draft in enumerate(draft_items, start=1):
                order_lines.append(NormalizedOrderLine(
                    line_number=idx,
                    original_text=draft.original_text,
                    product_phrase=draft.product_phrase,
                    quantity=draft.quantity,
                    unit=normalize_unit(draft.unit)
                ))

            logger.info(
                "Order parsed successfully: customer_id=%d, provider=%s, model=%s, lines=%d, latency_ms=%.2f",
                customer_id,
                provider_name,
                model_name,
                len(order_lines),
                duration_ms
            )

            return NormalizedOrder(
                company_id=company_id,
                customer_id=customer_id,
                source_type=source_type,
                raw_input=normalized_input.raw_text,
                items=order_lines
            )

        except Exception as e:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                "Order parsing failed: customer_id=%d, provider=%s, model=%s, latency_ms=%.2f, error=%s",
                customer_id,
                provider_name,
                model_name,
                duration_ms,
                str(e)
            )
            raise
