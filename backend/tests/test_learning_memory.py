import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.memory import CustomerProductAlias, HumanCorrection
from backend.app.services.learning_memory_service import LearningMemoryService
from backend.app.services.matching_engine import MatchingEngine
from backend.app.schemas.matching import MatchDecision


def setup_memory_catalog(db_session: Session):
    company = Company(name="Hellas Wholesale SA")
    db_session.add(company)
    db_session.flush()

    customer = Customer(company_id=company.id, customer_code="CUST-OUZERI", customer_name="Taverna Ouzeri")
    db_session.add(customer)
    db_session.flush()

    prod_salami = Product(
        company_id=company.id,
        sku="SKU-SALAMI",
        description="Σαλάμι Λευκάδος 500g",
        unit="piece",
        active=True
    )
    prod_turkey = Product(
        company_id=company.id,
        sku="SKU-TURKEY",
        description="Γαλοπούλα Καπνιστή 1kg",
        unit="piece",
        active=True
    )
    db_session.add_all([prod_salami, prod_turkey])
    db_session.commit()

    return {
        "company": company,
        "customer": customer,
        "prod_salami": prod_salami,
        "prod_turkey": prod_turkey
    }


def test_confirm_match_first_and_second_time(db_session):
    data = setup_memory_catalog(db_session)
    cust_id = data["customer"].id
    prod_id = data["prod_salami"].id

    # 1. First confirmation creates alias with confirmed_count = 1
    alias_1 = LearningMemoryService.confirm_match(
        db=db_session,
        customer_id=cust_id,
        product_id=prod_id,
        original_phrase="σαλαμακι"
    )
    assert alias_1.id is not None
    assert alias_1.customer_id == cust_id
    assert alias_1.product_id == prod_id
    assert alias_1.original_phrase == "σαλαμακι"
    assert alias_1.confirmed_count == 1
    assert alias_1.corrected_count == 0

    first_time = alias_1.last_confirmed_at

    # 2. Second confirmation increments confirmed_count = 2
    alias_2 = LearningMemoryService.confirm_match(
        db=db_session,
        customer_id=cust_id,
        product_id=prod_id,
        original_phrase="σαλαμακι"
    )
    assert alias_2.id == alias_1.id
    assert alias_2.confirmed_count == 2
    assert alias_2.last_confirmed_at >= first_time


def test_correct_match_records_audit_and_updates_alias(db_session):
    data = setup_memory_catalog(db_session)
    cust_id = data["customer"].id
    wrong_prod_id = data["prod_salami"].id
    correct_prod_id = data["prod_turkey"].id

    # Suppose previously there was an alias pointing to wrong product
    initial_alias = LearningMemoryService.confirm_match(
        db=db_session,
        customer_id=cust_id,
        product_id=wrong_prod_id,
        original_phrase="καπνιστο"
    )
    assert initial_alias.product_id == wrong_prod_id
    assert initial_alias.confirmed_count == 1

    # Operator corrects to correct_prod_id
    correction, updated_alias = LearningMemoryService.correct_match(
        db=db_session,
        customer_id=cust_id,
        correct_product_id=correct_prod_id,
        original_phrase="καπνιστο",
        suggested_product_id=wrong_prod_id,
        notes="Customer specifically meant smoked turkey, not salami"
    )

    # 1. Audit log verified
    assert correction.id is not None
    assert correction.customer_id == cust_id
    assert correction.suggested_product_id == wrong_prod_id
    assert correction.correct_product_id == correct_prod_id
    assert correction.original_phrase == "καπνιστο"
    assert "smoked turkey" in correction.notes

    # 2. Alias updated
    assert updated_alias.id == initial_alias.id
    assert updated_alias.product_id == correct_prod_id
    assert updated_alias.corrected_count == 1


def test_company_isolation_enforcement(db_session):
    """
    Attempting to confirm or correct using a product from another company must fail with ValueError.
    """
    data = setup_memory_catalog(db_session)
    other_comp = Company(name="Other Corp")
    db_session.add(other_comp)
    db_session.flush()

    foreign_prod = Product(
        company_id=other_comp.id,
        sku="FOREIGN-SKU",
        description="Foreign Item",
        active=True
    )
    db_session.add(foreign_prod)
    db_session.commit()

    with pytest.raises(ValueError, match="belongs to company"):
        LearningMemoryService.confirm_match(
            db=db_session,
            customer_id=data["customer"].id,
            product_id=foreign_prod.id,
            original_phrase="foreign item"
        )


def test_confidence_progression_with_confirmation_history(db_session):
    """
    Demonstrates that 1 confirmation is useful evidence (needs_review),
    while multiple confirmations build up to auto_accept (0.97).
    """
    data = setup_memory_catalog(db_session)
    comp_id = data["company"].id
    cust_id = data["customer"].id
    prod_id = data["prod_turkey"].id

    # 1. Confirm once
    LearningMemoryService.confirm_match(
        db=db_session,
        customer_id=cust_id,
        product_id=prod_id,
        original_phrase="κοκκινο"
    )

    # First match with 1 confirmation: base customer alias 0.90 -> needs_review
    res_1 = MatchingEngine.match_line(
        db=db_session,
        company_id=comp_id,
        customer_id=cust_id,
        line_number=1,
        original_text="1 κοκκινο",
        product_phrase="κοκκινο",
        quantity=1.0,
        unit="piece"
    )
    assert res_1.best_match.product_id == prod_id
    assert res_1.confidence.score == 0.90
    assert res_1.confidence.decision == MatchDecision.NEEDS_REVIEW

    # 2. Confirm 7 more times (total 8 confirmations)
    for _ in range(7):
        LearningMemoryService.confirm_match(
            db=db_session,
            customer_id=cust_id,
            product_id=prod_id,
            original_phrase="κοκκινο"
        )

    # Now match with 8 confirmations: score rises to 0.97 -> auto_accept!
    res_8 = MatchingEngine.match_line(
        db=db_session,
        company_id=comp_id,
        customer_id=cust_id,
        line_number=1,
        original_text="10 κοκκινα",
        product_phrase="κοκκινα",
        quantity=10.0,
        unit="piece"
    )
    assert res_8.best_match.product_id == prod_id
    assert res_8.confidence.score == 0.97
    assert res_8.confidence.decision == MatchDecision.AUTO_ACCEPT
    assert any("Confirmed 8 previous times" in r for r in res_8.confidence.reasons)
