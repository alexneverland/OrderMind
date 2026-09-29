"""Company policy is explicit and cannot leak between tenants."""

import pytest
from sqlalchemy import select

from backend.app.models.business_settings import CompanyBusinessSettings
from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.memory import CompanyProductUnitPreference
from backend.app.models.product import Product, Packaging
from backend.app.schemas.matching import MatchDecision
from backend.app.schemas.adapters import NormalizedInput
from backend.app.ai.mock_provider import MockAIProvider
from backend.app.services.business_settings_service import (
    effective_business_settings, validate_order_quantity_policy,
)
from backend.app.services.matching_engine import MatchingEngine
from backend.app.services.order_workflow_service import OrderWorkflowService
from backend.app.services.order_workflow_service import OrderApprovalError


def test_new_company_neutral_defaults_and_isolated_api_updates(client, db_session):
    a = Company(name="Configured company")
    b = Company(name="Neutral company")
    db_session.add_all([a, b])
    db_session.commit()
    neutral = client.get(f"/api/v1/companies/{b.id}/business-settings")
    assert neutral.status_code == 200
    assert neutral.json() == {
        "company_id": b.id, "bonus_enabled": False,
        "bonus_expression_mode": "disabled", "unitless_order_behavior": "require_review",
        "allow_packaging_conversion": False, "learn_unit_preferences": False,
    }
    assert db_session.get(CompanyBusinessSettings, b.id) is None
    invalid = client.put(f"/api/v1/companies/{a.id}/business-settings", json={
        "bonus_enabled": False, "bonus_expression_mode": "paid_plus_bonus",
    })
    assert invalid.status_code == 422
    updated = client.put(f"/api/v1/companies/{a.id}/business-settings", json={
        "bonus_enabled": True, "bonus_expression_mode": "paid_plus_bonus",
        "unitless_order_behavior": "learned_product_preference",
        "allow_packaging_conversion": True, "learn_unit_preferences": True,
    })
    assert updated.status_code == 200, updated.text
    assert client.get(f"/api/v1/companies/{b.id}/business-settings").json() == neutral.json()
    assert client.get("/api/v1/companies/99999/business-settings").status_code == 404
    validate_order_quantity_policy(effective_business_settings(db_session, a.id), "10+1", 1)
    with pytest.raises(ValueError, match="disabled"):
        validate_order_quantity_policy(effective_business_settings(db_session, b.id), "10+1", 1)
    with pytest.raises(ValueError, match="not enabled"):
        validate_order_quantity_policy(effective_business_settings(db_session, b.id), "10+1", 0)
    explicit = effective_business_settings(db_session, a.id).model_copy(update={"bonus_expression_mode": "explicit_only"})
    with pytest.raises(ValueError, match="not enabled"):
        validate_order_quantity_policy(explicit, "10+1", 1)
    validate_order_quantity_policy(explicit, "10+1 δωρο", 1)
    with pytest.raises(ValueError, match="explicit free-goods"):
        validate_order_quantity_policy(explicit, "10 1", 1)


def test_unitless_review_and_learning_are_company_scoped(db_session):
    a = Company(name="Learning company")
    b = Company(name="No learning company")
    db_session.add_all([a, b])
    db_session.flush()
    db_session.add(CompanyBusinessSettings(
        company_id=a.id, unitless_order_behavior="learned_product_preference",
        learn_unit_preferences=True,
    ))
    ca = Customer(company_id=a.id, customer_code="A", customer_name="A")
    cb = Customer(company_id=b.id, customer_code="B", customer_name="B")
    pa = Product(company_id=a.id, sku="SKU", description="Product", unit="piece")
    pb = Product(company_id=b.id, sku="SKU", description="Product", unit="piece")
    db_session.add_all([ca, cb, pa, pb])
    db_session.commit()

    for company, customer, product in ((a, ca, pa), (b, cb, pb)):
        match = MatchingEngine.match_line(db_session, company.id, customer.id, 1,
                                          "SKU 5", "SKU", 5, "piece")
        if company.id == b.id:
            assert match.confidence.decision == MatchDecision.NEEDS_REVIEW
        order = OrderWorkflowService.create_order_from_match(
            db_session, company.id, customer.id, "SKU 5", [match],
        )
        OrderWorkflowService.update_line_final_values(
            db_session, order.id, order.lines[0].id, final_unit="kg",
        )

    preferences = db_session.execute(select(CompanyProductUnitPreference)).scalars().all()
    assert [(p.company_id, p.product_id, p.unit) for p in preferences] == [(a.id, pa.id, "kg")]
    assert MatchingEngine.match_line(db_session, a.id, ca.id, 1, "SKU 7", "SKU", 7, "piece").final_unit == "kg"
    other = MatchingEngine.match_line(db_session, b.id, cb.id, 1, "SKU 7", "SKU", 7, "piece")
    assert other.unit == "unknown"
    assert other.final_unit is None
    assert other.confidence.decision == MatchDecision.NEEDS_REVIEW


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior,product_unit,preference,final_unit,decision", [
    ("require_review", "piece", None, None, MatchDecision.NEEDS_REVIEW),
    ("piece", "kg", None, "piece", MatchDecision.AUTO_ACCEPT),
    ("product_master_unit", "kg", None, "kg", MatchDecision.AUTO_ACCEPT),
    ("learned_product_preference", "piece", "case", "case", MatchDecision.NEEDS_REVIEW),
    ("learned_product_preference", "piece", None, None, MatchDecision.NEEDS_REVIEW),
])
async def test_unitless_evidence_then_company_policy(db_session, behavior, product_unit, preference, final_unit, decision):
    company = Company(name=f"Policy {behavior}")
    db_session.add(company)
    db_session.flush()
    if behavior != "require_review":
        db_session.add(CompanyBusinessSettings(
            company_id=company.id, unitless_order_behavior=behavior,
            learn_unit_preferences=behavior == "learned_product_preference",
        ))
    customer = Customer(company_id=company.id, customer_code="BUYER", customer_name="Buyer")
    product = Product(company_id=company.id, sku="SKU", description="Product", unit=product_unit)
    db_session.add_all([customer, product])
    db_session.flush()
    if preference:
        db_session.add(Packaging(company_id=company.id, product_id=product.id,
                                 package_type="case", pieces_per_case=12, unit="piece"))
        db_session.add(CompanyProductUnitPreference(company_id=company.id,
                                                     product_id=product.id, unit=preference))
    db_session.commit()

    extracted = await MockAIProvider().extract_order(NormalizedInput(raw_text="10 SKU", normalized_text=""))
    assert extracted[0].unit == "unknown"
    assert extracted[0].raw_unit is None
    assert extracted[0].unit_explicit is False
    match = MatchingEngine.match_line(db_session, company.id, customer.id, 1,
                                      "10 SKU", "SKU", 10, extracted[0].unit)
    assert match.unit == "unknown"
    assert match.final_unit == final_unit
    assert match.confidence.decision == decision
    order = OrderWorkflowService.create_order_from_match(db_session, company.id, customer.id, "10 SKU", [match])
    assert order.lines[0].requested_unit == "unknown"
    assert order.lines[0].final_unit == final_unit
    if final_unit is None:
        OrderWorkflowService.confirm_line(db_session, order.id, order.lines[0].id)
        with pytest.raises(OrderApprovalError, match="no resolved final unit"):
            OrderWorkflowService.approve_order(db_session, order.id)
        OrderWorkflowService.update_line_final_values(db_session, order.id, order.lines[0].id, final_unit="piece")
        approved = OrderWorkflowService.approve_order(db_session, order.id)
        assert approved.approved_snapshot["lines"][0]["requested_unit"] == "unknown"
        assert approved.approved_snapshot["lines"][0]["unit"] == "piece"


@pytest.mark.asyncio
async def test_explicit_piece_remains_customer_evidence(db_session):
    extracted = await MockAIProvider().extract_order(NormalizedInput(raw_text="10 pieces SKU", normalized_text=""))
    assert extracted[0].unit == "piece"
    assert extracted[0].raw_unit == "pieces"
    assert extracted[0].unit_explicit is True


def test_piece_policy_does_not_leak_to_other_company(db_session):
    a, b = Company(name="Piece policy"), Company(name="Review policy")
    db_session.add_all([a, b])
    db_session.flush()
    db_session.add(CompanyBusinessSettings(company_id=a.id, unitless_order_behavior="piece"))
    ca, cb = Customer(company_id=a.id, customer_code="A", customer_name="A"), Customer(company_id=b.id, customer_code="B", customer_name="B")
    pa, pb = Product(company_id=a.id, sku="SKU", description="Product", unit="piece"), Product(company_id=b.id, sku="SKU", description="Product", unit="piece")
    db_session.add_all([ca, cb, pa, pb])
    db_session.commit()
    for company, customer, final, decision in ((a, ca, "piece", MatchDecision.AUTO_ACCEPT),
                                                (b, cb, None, MatchDecision.NEEDS_REVIEW)):
        result = MatchingEngine.match_line(db_session, company.id, customer.id, 1, "10 SKU", "SKU", 10, "unknown")
        assert result.unit == "unknown"
        assert result.final_unit == final
        assert result.confidence.decision == decision
