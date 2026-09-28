import pytest
from unittest.mock import AsyncMock

from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.services.order_parsing_service import OrderParsingService
from backend.app.schemas.order import NormalizedOrder, NormalizedOrderLineDraft
from backend.app.ai.base import BaseAIProvider


class HallucinatingAIProvider(BaseAIProvider):
    name: str = "hallucinator"

    async def extract_order(self, normalized_input, context=None):
        return [
            NormalizedOrderLineDraft(
                original_text="10 γάλατα φρέσκα",  # completely absent from customer input!
                product_phrase="γάλατα φρέσκα",
                quantity=10.0,
                unit="piece"
            )
        ]


@pytest.mark.asyncio
async def test_order_parsing_service_success(db_session):
    """Verify OrderParsingService parses text into a validated NormalizedOrder."""
    comp = Company(name="Test Distributor S.A.")
    db_session.add(comp)
    db_session.commit()

    cust = Customer(company_id=comp.id, customer_code="CUST-77", customer_name="Super Market Alpha")
    db_session.add(cust)
    db_session.commit()

    service = OrderParsingService()

    raw_order_text = "Καλημέρα,\nθέλω 4 κούτες ζαμπόν 500\nκαι 10 τεμάχια μπέικον\nευχαριστώ!"

    normalized_order = await service.parse_order(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        text=raw_order_text,
        source_type="plain_text"
    )

    assert isinstance(normalized_order, NormalizedOrder)
    assert normalized_order.company_id == comp.id
    assert normalized_order.customer_id == cust.id
    assert normalized_order.raw_input == raw_order_text
    assert len(normalized_order.items) == 2

    line1 = normalized_order.items[0]
    assert line1.line_number == 1
    assert line1.quantity == 4.0
    assert line1.unit == "case"
    assert line1.raw_unit == "κούτες"
    assert line1.unit_explicit is True
    assert line1.product_phrase == "ζαμπόν 500"

    line2 = normalized_order.items[1]
    assert line2.line_number == 2
    assert line2.quantity == 10.0
    assert line2.unit == "piece"
    assert line2.raw_unit == "τεμάχια"
    assert line2.unit_explicit is True
    assert line2.product_phrase == "μπέικον"


@pytest.mark.asyncio
async def test_order_parsing_service_grounding_rejects_hallucination(db_session):
    """
    CRITICAL: Verify that if an AI provider returns an item that cannot be grounded
    in the raw customer input, it is rejected with a controlled ValueError.
    """
    comp = Company(name="Co 1")
    db_session.add(comp)
    db_session.commit()

    cust = Customer(company_id=comp.id, customer_code="C-1", customer_name="Customer 1")
    db_session.add(cust)
    db_session.commit()

    # Pass the hallucinating provider
    service = OrderParsingService(ai_provider=HallucinatingAIProvider())

    raw_input = "3 κούτες ζαμπόν 500"
    with pytest.raises(ValueError, match="cannot be grounded in customer input"):
        await service.parse_order(
            db=db_session,
            company_id=comp.id,
            customer_id=cust.id,
            text=raw_input,
            source_type="plain_text"
        )


@pytest.mark.asyncio
async def test_order_parsing_service_validation_errors(db_session):
    """Verify service validates company and customer existence."""
    comp1 = Company(name="Company 1")
    comp2 = Company(name="Company 2")
    db_session.add_all([comp1, comp2])
    db_session.commit()

    cust_comp2 = Customer(company_id=comp2.id, customer_code="C-2", customer_name="Customer of Co 2")
    db_session.add(cust_comp2)
    db_session.commit()

    service = OrderParsingService()

    # 1. Invalid company ID
    with pytest.raises(ValueError, match="Company with id 9999 not found"):
        await service.parse_order(db_session, company_id=9999, customer_id=cust_comp2.id, text="3 κούτες ζαμπόν")

    # 2. Customer does not belong to company 1
    with pytest.raises(ValueError, match="does not belong to Company"):
        await service.parse_order(db_session, company_id=comp1.id, customer_id=cust_comp2.id, text="3 κούτες ζαμπόν")
