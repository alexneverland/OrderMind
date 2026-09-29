"""Company policy is explicit and cannot leak between tenants."""

import pytest
from sqlalchemy import select

from backend.app.models.business_settings import CompanyBusinessSettings
from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.memory import CompanyProductUnitPreference
from backend.app.models.product import Product
from backend.app.schemas.matching import MatchDecision
from backend.app.services.business_settings_service import (
    effective_business_settings, validate_order_quantity_policy,
)
from backend.app.services.matching_engine import MatchingEngine
from backend.app.services.order_workflow_service import OrderWorkflowService


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
    assert other.final_unit == "piece"
    assert other.confidence.decision == MatchDecision.NEEDS_REVIEW
