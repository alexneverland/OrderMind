import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.company import Company
from backend.app.models.business_settings import CompanyBusinessSettings
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.order import Order, OrderLine
from backend.app.models.memory import CustomerProductAlias, HumanCorrection
from backend.app.services.learning_memory_service import LearningMemoryService, AliasConflictError
from backend.app.services.matching_engine import MatchingEngine
from backend.app.schemas.matching import MatchDecision



def setup_memory_catalog(db_session: Session):
    company = Company(name="Hellas Wholesale SA")
    db_session.add(company)
    db_session.flush()
    db_session.add(CompanyBusinessSettings(company_id=company.id, unitless_order_behavior="piece"))

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


def test_correction_confirmation_reset_and_no_leak(db_session):
    """
    Before: 'κοκκινο' -> Product A, confirmed_count = 20
    Operator corrects to Product B.
    After:
    - product_id = Product B
    - confirmed_count = 1 (RESET! 20 old confirmations must NOT transfer)
    - corrected_count = previous + 1
    - Confidence of new mapping is based on new count (1), NOT the old 20!
    """
    data = setup_memory_catalog(db_session)
    comp_id = data["company"].id
    cust_id = data["customer"].id
    prod_a_id = data["prod_salami"].id
    prod_b_id = data["prod_turkey"].id

    # Create alias with 20 confirmations for Product A
    alias = CustomerProductAlias(
        customer_id=cust_id,
        product_id=prod_a_id,
        original_phrase="κοκκινο",
        normalized_phrase="κοκκινο",
        confirmed_count=20,
        corrected_count=0,
        active=True
    )
    db_session.add(alias)
    db_session.commit()

    # Operator corrects to Product B
    correction, updated_alias = LearningMemoryService.correct_match(
        db=db_session,
        customer_id=cust_id,
        correct_product_id=prod_b_id,
        original_phrase="κοκκινο",
        suggested_product_id=prod_a_id,
        notes="Customer meant Turkey, not Salami"
    )

    # Assertions on database state
    assert updated_alias.product_id == prod_b_id
    assert updated_alias.confirmed_count == 1  # Crucial: reset to 1
    assert updated_alias.corrected_count == 1

    # Now matching 'κοκκινο' must evaluate against Product B with count=1, NOT count=20
    res = MatchingEngine.match_line(
        db=db_session,
        company_id=comp_id,
        customer_id=cust_id,
        line_number=1,
        original_text="1 κοκκινο",
        product_phrase="κοκκινο",
        quantity=1.0,
        unit="piece"
    )
    assert res.best_match.product_id == prod_b_id
    # Base 0.90 + 0 (conf count 1) - 0.05 (1 correction penalty) = 0.85 -> needs_review
    assert res.confidence.score == 0.85
    assert res.confidence.decision == MatchDecision.NEEDS_REVIEW
    # It must NOT be auto_accepted (which would happen if 20 confirmations had leaked)


def test_confirm_match_conflict_error_prevents_silent_mutation(db_session):
    """
    Alias already points to Product A with confirmed_count = 5.
    Calling confirm_match with Product B must raise AliasConflictError.
    Must NOT silently mutate alias or transfer counts.
    """
    data = setup_memory_catalog(db_session)
    cust_id = data["customer"].id
    prod_a_id = data["prod_salami"].id
    prod_b_id = data["prod_turkey"].id

    alias = CustomerProductAlias(
        customer_id=cust_id,
        product_id=prod_a_id,
        original_phrase="κοκκινο",
        normalized_phrase="κοκκινο",
        confirmed_count=5,
        corrected_count=0,
        active=True
    )
    db_session.add(alias)
    db_session.commit()

    # Attempting to confirm a conflicting product must fail
    with pytest.raises(AliasConflictError, match="points to a different product"):
        LearningMemoryService.confirm_match(
            db=db_session,
            customer_id=cust_id,
            product_id=prod_b_id,
            original_phrase="κοκκινο"
        )

    # Verify alias was NOT altered
    db_session.refresh(alias)
    assert alias.product_id == prod_a_id
    assert alias.confirmed_count == 5
    assert alias.corrected_count == 0

    # Verify no HumanCorrection audit record was accidentally created
    corrections = db_session.execute(select(HumanCorrection)).scalars().all()
    assert len(corrections) == 0


def test_correct_match_audit_trail_resolves_conflict(db_session):
    """
    Conflict is cleanly and transactionally resolved via correct_match.
    Creates HumanCorrection and updates alias properly.
    """
    data = setup_memory_catalog(db_session)
    cust_id = data["customer"].id
    prod_a_id = data["prod_salami"].id
    prod_b_id = data["prod_turkey"].id

    alias = CustomerProductAlias(
        customer_id=cust_id,
        product_id=prod_a_id,
        original_phrase="κοκκινο",
        normalized_phrase="κοκκινο",
        confirmed_count=3,
        corrected_count=0,
        active=True
    )
    db_session.add(alias)
    db_session.commit()

    # Properly correct the match
    correction, updated_alias = LearningMemoryService.correct_match(
        db=db_session,
        customer_id=cust_id,
        correct_product_id=prod_b_id,
        original_phrase="κοκκινο",
        suggested_product_id=prod_a_id,
        notes="Operator confirmed customer wants Turkey"
    )

    assert correction.id is not None
    assert correction.customer_id == cust_id
    assert correction.suggested_product_id == prod_a_id
    assert correction.correct_product_id == prod_b_id

    assert updated_alias.product_id == prod_b_id
    assert updated_alias.confirmed_count == 1
    assert updated_alias.corrected_count == 1


def test_correct_match_stores_order_and_line_reference(db_session):
    """
    Verifies that correct_match stores both order_id and order_line_id
    in HumanCorrection, and links bidirectionally via ORM relationships.
    """
    data = setup_memory_catalog(db_session)
    comp_id = data["company"].id
    cust_id = data["customer"].id
    prod_a_id = data["prod_salami"].id
    prod_b_id = data["prod_turkey"].id

    order = Order(
        company_id=comp_id,
        customer_id=cust_id,
        order_number="ORD-AUDIT-001",
        raw_input="1 κοκκινο"
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="1 κοκκινο",
        product_phrase="κοκκινο",
        requested_quantity=1.0,
        requested_unit="piece"
    )
    db_session.add(line)
    db_session.commit()

    correction, alias = LearningMemoryService.correct_match(
        db=db_session,
        customer_id=cust_id,
        correct_product_id=prod_b_id,
        original_phrase="κοκκινο",
        suggested_product_id=prod_a_id,
        order_id=order.id,
        line_id=line.id,
        notes="Corrected during order intake review"
    )

    # Verify both order_id and order_line_id are persisted in HumanCorrection
    assert correction.id is not None
    assert correction.order_id == order.id
    assert correction.order_line_id == line.id

    # Verify ORM relationships
    assert correction.order_line is not None
    assert correction.order_line.id == line.id
    assert correction.order is not None
    assert correction.order.id == order.id

    # Verify line.corrections back-population
    saved_line = db_session.execute(select(OrderLine).where(OrderLine.id == line.id)).scalar_one()
    assert len(saved_line.corrections) == 1
    assert saved_line.corrections[0].id == correction.id


def test_suggested_product_company_isolation(db_session):
    """
    Suggested product must belong to customer's company.
    If not, or if non-existent, raise ValueError and perform zero mutations.
    """
    data = setup_memory_catalog(db_session)
    cust_id = data["customer"].id
    correct_prod_id = data["prod_salami"].id

    # Foreign company and product
    other_comp = Company(name="Foreign Corp")
    db_session.add(other_comp)
    db_session.flush()

    foreign_prod = Product(
        company_id=other_comp.id,
        sku="FOREIGN-SUGGEST",
        description="Foreign Suggested Product",
        active=True
    )
    db_session.add(foreign_prod)
    db_session.commit()

    initial_corrections_count = len(db_session.execute(select(HumanCorrection)).scalars().all())
    initial_aliases_count = len(db_session.execute(select(CustomerProductAlias)).scalars().all())

    # Case 1: Cross-company suggested product raises ValueError
    with pytest.raises(ValueError, match="belongs to company"):
        LearningMemoryService.correct_match(
            db=db_session,
            customer_id=cust_id,
            correct_product_id=correct_prod_id,
            original_phrase="foreign phrase",
            suggested_product_id=foreign_prod.id
        )

    # Zero mutations check
    assert len(db_session.execute(select(HumanCorrection)).scalars().all()) == initial_corrections_count
    assert len(db_session.execute(select(CustomerProductAlias)).scalars().all()) == initial_aliases_count

    # Case 2: Non-existent suggested product raises ValueError
    with pytest.raises(ValueError, match="does not exist"):
        LearningMemoryService.correct_match(
            db=db_session,
            customer_id=cust_id,
            correct_product_id=correct_prod_id,
            original_phrase="foreign phrase",
            suggested_product_id=999999
        )

    # Zero mutations check
    assert len(db_session.execute(select(HumanCorrection)).scalars().all()) == initial_corrections_count
    assert len(db_session.execute(select(CustomerProductAlias)).scalars().all()) == initial_aliases_count


def test_order_and_line_consistency_validations(db_session):
    """
    Verifies order/line validation:
    - Line does not exist -> ValueError
    - Line does not belong to specified order -> ValueError
    - Order belongs to different company -> ValueError
    - Order belongs to different customer -> ValueError
    - Only line_id provided -> resolves order_id automatically
    - All validation failures cause zero mutations
    """
    data = setup_memory_catalog(db_session)
    comp_id = data["company"].id
    cust_id = data["customer"].id
    prod_a_id = data["prod_salami"].id
    prod_b_id = data["prod_turkey"].id

    order_1 = Order(company_id=comp_id, customer_id=cust_id, order_number="ORD-VAL-1", raw_input="line 1")
    order_2 = Order(company_id=comp_id, customer_id=cust_id, order_number="ORD-VAL-2", raw_input="line 2")
    db_session.add_all([order_1, order_2])
    db_session.flush()

    line_1 = OrderLine(order_id=order_1.id, line_number=1, original_text="1 salami", product_phrase="salami")
    db_session.add(line_1)
    db_session.commit()

    # Rival company and customer
    other_comp = Company(name="Rival Wholesale")
    db_session.add(other_comp)
    db_session.flush()
    other_cust = Customer(company_id=other_comp.id, customer_code="RIVAL-CUST", customer_name="Rival")
    db_session.add(other_cust)
    db_session.flush()
    other_order = Order(company_id=other_comp.id, customer_id=other_cust.id, order_number="ORD-RIVAL-1", raw_input="rival")
    db_session.add(other_order)
    db_session.commit()

    # Same company but different customer
    peer_cust = Customer(company_id=comp_id, customer_code="PEER-CUST", customer_name="Peer Customer")
    db_session.add(peer_cust)
    db_session.flush()
    peer_order = Order(company_id=comp_id, customer_id=peer_cust.id, order_number="ORD-PEER-1", raw_input="peer")
    db_session.add(peer_order)
    db_session.commit()

    initial_corrections_count = len(db_session.execute(select(HumanCorrection)).scalars().all())

    # 1. Non-existent line_id
    with pytest.raises(ValueError, match="Order line with id 999999 does not exist"):
        LearningMemoryService.correct_match(
            db=db_session,
            customer_id=cust_id,
            correct_product_id=prod_b_id,
            original_phrase="salami",
            line_id=999999
        )
    assert len(db_session.execute(select(HumanCorrection)).scalars().all()) == initial_corrections_count

    # 2. Line belongs to order_1, but order_id=order_2 is passed
    with pytest.raises(ValueError, match="belongs to order .* not order"):
        LearningMemoryService.correct_match(
            db=db_session,
            customer_id=cust_id,
            correct_product_id=prod_b_id,
            original_phrase="salami",
            order_id=order_2.id,
            line_id=line_1.id
        )
    assert len(db_session.execute(select(HumanCorrection)).scalars().all()) == initial_corrections_count

    # 3. Order belongs to different company
    with pytest.raises(ValueError, match="belongs to company"):
        LearningMemoryService.correct_match(
            db=db_session,
            customer_id=cust_id,
            correct_product_id=prod_b_id,
            original_phrase="salami",
            order_id=other_order.id
        )
    assert len(db_session.execute(select(HumanCorrection)).scalars().all()) == initial_corrections_count

    # 4. Order belongs to different customer in same company
    with pytest.raises(ValueError, match="belongs to customer"):
        LearningMemoryService.correct_match(
            db=db_session,
            customer_id=cust_id,
            correct_product_id=prod_b_id,
            original_phrase="salami",
            order_id=peer_order.id
        )
    assert len(db_session.execute(select(HumanCorrection)).scalars().all()) == initial_corrections_count

    # 5. Only line_id provided: automatically resolves order_id
    correction, alias = LearningMemoryService.correct_match(
        db=db_session,
        customer_id=cust_id,
        correct_product_id=prod_b_id,
        original_phrase="salami",
        line_id=line_1.id
    )
    assert correction.order_line_id == line_1.id
    assert correction.order_id == order_1.id
    assert len(db_session.execute(select(HumanCorrection)).scalars().all()) == initial_corrections_count + 1

