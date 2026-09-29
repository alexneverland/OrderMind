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


@pytest.mark.asyncio
async def test_ai_quantity_evidence_handles_two_products_and_bonus(db_session):
    company = Company(name="AI order company")
    db_session.add(company)
    db_session.commit()
    customer = Customer(company_id=company.id, customer_code="AI", customer_name="AI customer")
    db_session.add(customer)
    db_session.commit()
    row = "131382 | ΦΡΑΝΚ 500ΓΡ | TEM | 56+6 | 180534 | ΩΜΟΠΛΑΤΗ | ΚΙΛ | 10KIB+1KIB"

    class Provider(BaseAIProvider):
        name: str = "evidence"

        async def extract_order(self, normalized_input, context=None):
            return [
                NormalizedOrderLineDraft(
                    original_text="131382 | ΦΡΑΝΚ 500ΓΡ | TEM | 56+6",
                    product_phrase="131382", quantity=56, bonus_quantity=6,
                    quantity_text="56+6", unit="piece",
                ),
                NormalizedOrderLineDraft(
                    original_text="180534 | ΩΜΟΠΛΑΤΗ | ΚΙΛ | 10KIB+1KIB",
                    product_phrase="180534", quantity=10, bonus_quantity=1,
                    quantity_text="10KIB+1KIB", unit="case", raw_unit="KIB", unit_explicit=True,
                ),
            ]

    order = await OrderParsingService(ai_provider=Provider()).parse_order(
        db_session, company.id, customer.id, row
    )
    assert [(item.product_phrase, item.quantity, item.bonus_quantity, item.unit) for item in order.items] == [
        ("131382", 56.0, 6.0, "piece"), ("180534", 10.0, 1.0, "case"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", ["10ΚΙΒ+1", "ΚΙΒ 10+1", "10 cases + 1"])
async def test_bare_bonus_inherits_explicit_quantity_unit(db_session, expression):
    company = Company(name=f"Bonus unit {expression}")
    db_session.add(company)
    db_session.flush()
    customer = Customer(company_id=company.id, customer_code="BU", customer_name="Bonus buyer")
    db_session.add(customer)
    db_session.commit()
    row = f"180534 | ΩΜΟΠΛΑΤΗ | {expression}"

    class Provider(BaseAIProvider):
        name: str = "bonus-unit"

        async def extract_order(self, normalized_input, context=None):
            # A provider may label the bare +1 as a piece. The verbatim
            # quantity expression is the authority for the shared unit.
            return [NormalizedOrderLineDraft(
                original_text=row, product_phrase="180534", quantity=10,
                bonus_quantity=1, quantity_text=expression, unit="piece",
            )]

    order = await OrderParsingService(ai_provider=Provider()).parse_order(
        db_session, company.id, customer.id, row
    )
    assert order.items[0].unit == "case"
    assert order.items[0].bonus_quantity == 1
    assert order.items[0].unit_explicit is True


@pytest.mark.asyncio
async def test_mixed_explicit_paid_and_bonus_units_are_not_silently_combined(db_session):
    company = Company(name="Mixed bonus units")
    db_session.add(company)
    db_session.flush()
    customer = Customer(company_id=company.id, customer_code="MU", customer_name="Mixed buyer")
    db_session.add(customer)
    db_session.commit()
    row = "180534 | 10 ΚΙΒ + 1 ΤΕΜ"

    class Provider(BaseAIProvider):
        name: str = "mixed-units"

        async def extract_order(self, normalized_input, context=None):
            return [NormalizedOrderLineDraft(
                original_text=row, product_phrase="180534", quantity=10,
                bonus_quantity=1, quantity_text="10 ΚΙΒ + 1 ΤΕΜ", unit="case",
                raw_unit="ΚΙΒ", unit_explicit=True,
            )]

    with pytest.raises(ValueError, match="different units"):
        await OrderParsingService(ai_provider=Provider()).parse_order(
            db_session, company.id, customer.id, row
        )


@pytest.mark.asyncio
async def test_ai_cannot_take_measure_column_as_order_unit(db_session):
    company = Company(name="Measure company")
    db_session.add(company)
    db_session.commit()
    customer = Customer(company_id=company.id, customer_code="MM", customer_name="Measure customer")
    db_session.add(customer)
    db_session.commit()
    row = "180406 | ΠΑΡΙΖΑ ΦΟΡΜΑ 3.0 ΚΙΛ | ΚΙΛ | 35"

    class Provider(BaseAIProvider):
        name: str = "measure"

        async def extract_order(self, normalized_input, context=None):
            return [NormalizedOrderLineDraft(
                original_text=row, product_phrase="180406", quantity=35,
                quantity_text="35", unit="kg", raw_unit="ΚΙΛ", unit_explicit=True,
            )]

    order = await OrderParsingService(ai_provider=Provider()).parse_order(
        db_session, company.id, customer.id, row
    )
    assert order.items[0].quantity == 35
    assert order.items[0].unit == "piece"
