import time
import logging
import re
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

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
from backend.app.core.text_normalizer import (
    normalize_text,
    is_quantity_grounded_in_span,
    is_unit_grounded_in_span,
    quantity_expression_units,
)
from backend.app.services.business_settings_service import effective_business_settings, validate_order_quantity_policy

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
        Input -> Adapter -> NormalizedInput -> AI Extraction -> Grounding Validation -> Validated NormalizedOrder
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
        business_settings = effective_business_settings(db, company_id)

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
                context={"company_id": company_id, "customer_id": customer_id,
                         "bonus_expression_mode": business_settings.bonus_expression_mode}
            )
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # 6. Build sequential, grounded, validated lines
            order_lines: List[NormalizedOrderLine] = []
            for idx, draft in enumerate(draft_items, start=1):
                validate_order_quantity_policy(business_settings, draft.quantity_text, draft.bonus_quantity)
                expression_units = quantity_expression_units(draft.quantity_text)
                distinct_units = {unit for unit, _ in expression_units}
                if len(distinct_units) > 1:
                    raise ValueError(
                        f"Item '{draft.original_text}' has different units in one quantity expression; "
                        "split or correct it before approval."
                    )
                if expression_units:
                    # A single explicit unit applies to both paid and bare bonus
                    # quantities regardless of word order or spacing.
                    draft = draft.model_copy(update={
                        "unit": expression_units[0][0],
                        "raw_unit": expression_units[0][1],
                        "unit_explicit": True,
                    })
                if draft.quantity_text and not re.search(r"[^\W\d_]", draft.quantity_text, re.UNICODE):
                    # A bare numeric expression has no requested unit. A unit
                    # elsewhere in the product name or spreadsheet is metadata.
                    draft = draft.model_copy(update={
                        "unit": "piece", "raw_unit": None, "unit_explicit": False,
                    })
                # Grounding verification: Check that draft original_text or product_phrase exists in input
                if not normalize_text(draft.original_text) or normalize_text(draft.original_text) not in normalize_text(normalized_input.raw_text):
                    raise ValueError(
                        f"Extracted item '{draft.original_text}' cannot be grounded in customer input (hallucination detected)."
                    )
                if normalize_text(draft.product_phrase) not in normalize_text(draft.original_text):
                    raise ValueError(
                        f"Extracted product '{draft.product_phrase}' cannot be grounded in its order item."
                    )

                # Quantity grounding check
                if not is_quantity_grounded_in_span(
                    draft.quantity, draft.original_text, normalized_input.raw_text,
                    draft.product_phrase, draft.quantity_text, draft.bonus_quantity,
                ):
                    raise ValueError(
                        f"Extracted quantity {draft.quantity} for item '{draft.original_text}' cannot be grounded in customer input (contradictory extraction)."
                    )

                # Unit grounding check
                if not is_unit_grounded_in_span(
                    draft.unit, draft.raw_unit, draft.unit_explicit,
                    draft.original_text, normalized_input.raw_text,
                    draft.product_phrase, draft.quantity_text,
                ):
                    raise ValueError(
                        f"Extracted unit '{draft.unit}' for item '{draft.original_text}' cannot be grounded in customer input (contradictory extraction)."
                    )

                order_lines.append(NormalizedOrderLine(
                    line_number=idx,
                    original_text=draft.original_text,
                    product_phrase=draft.product_phrase,
                    quantity=draft.quantity,
                    unit=draft.unit,
                    raw_unit=draft.raw_unit,
                    unit_explicit=draft.unit_explicit,
                    quantity_text=draft.quantity_text,
                    bonus_quantity=draft.bonus_quantity,
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
                type(e).__name__
            )
            raise
