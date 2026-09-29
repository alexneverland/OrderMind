import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.company import Company
from backend.app.models.business_settings import CompanyBusinessSettings
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.memory import CustomerProductAlias, HumanCorrection
from backend.app.schemas.workflow import OrderStatus, OrderLineStatus
from backend.app.schemas.matching import LineMatchResult, MatchedProductInfo, ConfidenceResult, MatchDecision
from backend.app.services.order_workflow_service import (
    OrderWorkflowService,
    OrderApprovalError,
)
from backend.app.services.matching_engine import MatchingEngine


def setup_workflow_data(db_session: Session):
    company = Company(name="Hellas Catering")
    db_session.add(company)
    db_session.flush()

    customer = Customer(company_id=company.id, customer_code="CUST-ALPHA", customer_name="Alpha Restaurant")
    prod1 = Product(company_id=company.id, sku="SKU-7843", description="Γαλοπούλα Καπνιστή 1kg", unit="piece", active=True)
    prod2 = Product(company_id=company.id, sku="SKU-100", description="Σαλάμι Μπύρας 300g", unit="piece", active=True)
    db_session.add_all([customer, prod1, prod2])
    db_session.commit()

    return {
        "company": company,
        "customer": customer,
        "prod1": prod1,
        "prod2": prod2
    }


def test_operator_unit_correction_is_recalled_for_all_company_customers(db_session):
    data = setup_workflow_data(db_session)
    db_session.add(CompanyBusinessSettings(company_id=data["company"].id, unitless_order_behavior="learned_product_preference", learn_unit_preferences=True))
    db_session.commit()
    product = data["prod1"]
    product.unit = "kg"
    db_session.commit()
    first = MatchingEngine.match_line(
        db_session, data["company"].id, data["customer"].id, 1,
        product.sku + " 5", product.sku, 5, "piece",
    )
    assert first.final_unit == "piece"
    order = OrderWorkflowService.create_order_from_match(
        db_session, data["company"].id, data["customer"].id,
        product.sku + " 5", [first],
    )
    OrderWorkflowService.update_line_final_values(
        db_session, order.id, order.lines[0].id, final_unit="kg",
    )
    learned = MatchingEngine.match_line(
        db_session, data["company"].id, data["customer"].id, 1,
        product.sku + " 7", product.sku, 7, "piece",
    )
    assert learned.unit == "piece"
    assert learned.final_unit == "kg"
    assert learned.confidence.decision == MatchDecision.NEEDS_REVIEW
    other_customer = Customer(
        company_id=data["company"].id, customer_code="OTHER", customer_name="Other buyer",
    )
    db_session.add(other_customer)
    db_session.commit()
    for_other = MatchingEngine.match_line(
        db_session, data["company"].id, other_customer.id, 1,
        product.sku + " 7", product.sku, 7, "piece",
    )
    assert for_other.final_unit == "kg"
    explicit_piece = MatchingEngine.match_line(
        db_session, data["company"].id, other_customer.id, 1,
        product.sku + " 7 τεμάχια", product.sku, 7, "piece", "τεμάχια", True,
    )
    assert explicit_piece.final_unit == "piece"


def test_persist_matched_order_preserves_requested_and_final_values(db_session):
    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod1 = data["prod1"]

    line_match = LineMatchResult(
        line_number=1,
        original_text="10 κοκκινα",
        product_phrase="κοκκινα",
        quantity=10.0,
        unit="piece",
        raw_unit=None,
        unit_explicit=False,
        best_match=MatchedProductInfo(
            product_id=prod1.id,
            sku=prod1.sku,
            description=prod1.description,
            unit=prod1.unit
        ),
        confidence=ConfidenceResult(
            score=0.97,
            decision=MatchDecision.AUTO_ACCEPT,
            reasons=["+ Customer alias exact match", "+ Confirmed 8 times"]
        ),
        alternatives=[]
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="10 κοκκινα",
        lines=[line_match]
    )

    assert order.id is not None
    assert order.order_number.startswith("ORD-")
    assert order.status == OrderStatus.PENDING_REVIEW.value
    assert order.overall_confidence == 0.97
    assert len(order.lines) == 1

    line = order.lines[0]
    # Requested fields
    assert line.original_text == "10 κοκκινα"
    assert line.product_phrase == "κοκκινα"
    assert line.requested_quantity == 10.0
    assert line.requested_unit == "piece"
    assert line.unit_explicit is False

    # Matched/final fields
    assert line.matched_product_id == prod1.id
    assert line.final_sku == prod1.sku
    assert line.final_quantity == 10.0
    assert line.final_unit == "piece"
    assert line.confidence_score == 0.97
    assert line.status == OrderLineStatus.AUTO_ACCEPTED.value


def test_approval_succeeds_when_all_lines_auto_accepted(db_session):
    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod1 = data["prod1"]

    line_match = LineMatchResult(
        line_number=1,
        original_text="5 γαλοπουλες",
        product_phrase="γαλοπουλες",
        quantity=5.0,
        unit="piece",
        best_match=MatchedProductInfo(
            product_id=prod1.id,
            sku=prod1.sku,
            description=prod1.description,
            unit=prod1.unit
        ),
        confidence=ConfidenceResult(
            score=0.95,
            decision=MatchDecision.AUTO_ACCEPT,
            reasons=["+ Exact description match"]
        )
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="5 γαλοπουλες",
        lines=[line_match]
    )

    approved = OrderWorkflowService.approve_order(db=db_session, order_id=order.id)
    assert approved.status == OrderStatus.APPROVED.value
    assert approved.approved_at is not None
    assert approved.confirmed_at is not None


def test_approval_blocked_by_needs_review_and_unresolved_lines(db_session):
    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod1 = data["prod1"]

    line_needs_review = LineMatchResult(
        line_number=1,
        original_text="1 καπνιστο",
        product_phrase="καπνιστο",
        quantity=1.0,
        unit="piece",
        best_match=MatchedProductInfo(
            product_id=prod1.id,
            sku=prod1.sku,
            description=prod1.description,
            unit=prod1.unit
        ),
        confidence=ConfidenceResult(
            score=0.82,
            decision=MatchDecision.NEEDS_REVIEW,
            reasons=["+ Fuzzy match", "? Ambiguous"]
        )
    )
    line_unresolved = LineMatchResult(
        line_number=2,
        original_text="3 αγνωστο προιον",
        product_phrase="αγνωστο προιον",
        quantity=3.0,
        unit="piece",
        best_match=None,
        confidence=ConfidenceResult(
            score=0.20,
            decision=MatchDecision.UNRESOLVED,
            reasons=["- No candidate matches threshold"]
        )
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="1 καπνιστο\n3 αγνωστο προιον",
        lines=[line_needs_review, line_unresolved]
    )

    with pytest.raises(OrderApprovalError, match=r"cannot be approved because 2 line\(s\) still require review"):
        OrderWorkflowService.approve_order(db=db_session, order_id=order.id)

    # Order status remains pending_review
    assert order.status == OrderStatus.PENDING_REVIEW.value


def test_manual_confirmation_unblocks_approval(db_session):
    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod1 = data["prod1"]

    line_needs_review = LineMatchResult(
        line_number=1,
        original_text="1 καπνιστο",
        product_phrase="καπνιστο",
        quantity=1.0,
        unit="piece",
        best_match=MatchedProductInfo(
            product_id=prod1.id,
            sku=prod1.sku,
            description=prod1.description,
            unit=prod1.unit
        ),
        confidence=ConfidenceResult(
            score=0.82,
            decision=MatchDecision.NEEDS_REVIEW,
            reasons=["+ Fuzzy match"]
        )
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="1 καπνιστο",
        lines=[line_needs_review]
    )
    line_id = order.lines[0].id

    # 1. Approval initially fails
    with pytest.raises(OrderApprovalError, match=r"1 line\(s\) still require review"):
        OrderWorkflowService.approve_order(db=db_session, order_id=order.id)

    # 2. Operator confirms the line match
    confirmed_line = OrderWorkflowService.confirm_line(
        db=db_session,
        order_id=order.id,
        line_id=line_id
    )
    assert confirmed_line.status == OrderLineStatus.CONFIRMED.value

    # Confirmed line fed into Learning Memory
    alias = db_session.execute(
        select(CustomerProductAlias).where(
            CustomerProductAlias.customer_id == cust.id,
            CustomerProductAlias.normalized_phrase == "καπνιστο"
        )
    ).scalar_one()
    assert alias.product_id == prod1.id

    # 3. Now approval succeeds
    approved_order = OrderWorkflowService.approve_order(db=db_session, order_id=order.id)
    assert approved_order.status == OrderStatus.APPROVED.value


def test_manual_correction_updates_order_line_and_learning_memory(db_session):
    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_wrong = data["prod1"]
    prod_correct = data["prod2"]

    line_unresolved = LineMatchResult(
        line_number=1,
        original_text="2 σαλαμακι",
        product_phrase="σαλαμακι",
        quantity=2.0,
        unit="piece",
        best_match=MatchedProductInfo(
            product_id=prod_wrong.id,
            sku=prod_wrong.sku,
            description=prod_wrong.description,
            unit=prod_wrong.unit
        ),
        confidence=ConfidenceResult(
            score=0.70,
            decision=MatchDecision.NEEDS_REVIEW,
            reasons=["? Low confidence match"]
        )
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="2 σαλαμακι",
        lines=[line_unresolved]
    )
    line_id = order.lines[0].id

    # Correct line
    correction, corrected_line = OrderWorkflowService.correct_line(
        db=db_session,
        order_id=order.id,
        line_id=line_id,
        correct_product_id=prod_correct.id,
        notes="Customer meant salami, not turkey"
    )

    # Verify line values
    assert corrected_line.status == OrderLineStatus.CORRECTED.value
    assert corrected_line.matched_product_id == prod_correct.id
    assert corrected_line.final_sku == prod_correct.sku
    assert corrected_line.final_unit == prod_correct.unit
    # Original requested phrase and quantity preserved
    assert corrected_line.original_text == "2 σαλαμακι"
    assert corrected_line.product_phrase == "σαλαμακι"
    assert corrected_line.requested_quantity == 2.0

    # Verify audit record
    assert correction.order_id == order.id
    assert correction.order_line_id == line_id
    assert correction.correct_product_id == prod_correct.id

    # Verify order can now be approved
    approved = OrderWorkflowService.approve_order(db=db_session, order_id=order.id)
    assert approved.status == OrderStatus.APPROVED.value


def test_operator_modifies_final_values_preserves_requested(db_session):
    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod1 = data["prod1"]

    line_match = LineMatchResult(
        line_number=1,
        original_text="3 κουτες ζαμπον",
        product_phrase="ζαμπον",
        quantity=3.0,
        unit="case",
        raw_unit="κουτες",
        unit_explicit=True,
        best_match=MatchedProductInfo(
            product_id=prod1.id,
            sku=prod1.sku,
            description=prod1.description,
            unit="piece"
        ),
        confidence=ConfidenceResult(
            score=0.92,
            decision=MatchDecision.AUTO_ACCEPT,
            reasons=["+ High confidence"]
        )
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="3 κουτες ζαμπον",
        lines=[line_match]
    )
    line_id = order.lines[0].id

    # Operator updates final packaging conversion manually: 3 cases -> 36 pieces
    updated_line = OrderWorkflowService.update_line_final_values(
        db=db_session,
        order_id=order.id,
        line_id=line_id,
        final_quantity=36.0,
        final_unit="piece"
    )

    # Requested values remain untouched
    assert updated_line.requested_quantity == 3.0
    assert updated_line.requested_unit == "case"
    assert updated_line.raw_unit == "κουτες"
    assert updated_line.unit_explicit is True

    # Final values reflect operator input
    assert updated_line.final_quantity == 36.0
    assert updated_line.final_unit == "piece"


def test_canonical_order_structure(db_session):
    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod1 = data["prod1"]

    line_match = LineMatchResult(
        line_number=1,
        original_text="10 τεμ γαλοπουλα",
        product_phrase="γαλοπουλα",
        quantity=10.0,
        unit="piece",
        best_match=MatchedProductInfo(
            product_id=prod1.id,
            sku=prod1.sku,
            description=prod1.description,
            unit="piece"
        ),
        confidence=ConfidenceResult(score=0.98, decision=MatchDecision.AUTO_ACCEPT)
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="10 τεμ γαλοπουλα",
        lines=[line_match]
    )
    OrderWorkflowService.approve_order(db=db_session, order_id=order.id)

    canonical = OrderWorkflowService.get_canonical_order(order)
    assert canonical.order_id == order.id
    assert canonical.status == "approved"
    assert canonical.customer.customer_code == "CUST-ALPHA"
    assert len(canonical.items) == 1
    assert canonical.items[0].sku == "SKU-7843"
    assert canonical.items[0].quantity == 10.0
    assert canonical.items[0].unit == "piece"


def test_approved_order_is_immutable(db_session):
    """
    Verify that an approved order is strictly immutable:
    confirm_line, correct_line, and update_line_final_values must all reject modifications.
    """
    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod1 = data["prod1"]
    prod2 = data["prod2"]

    line_match = LineMatchResult(
        line_number=1,
        original_text="10 τεμ γαλοπουλα",
        product_phrase="γαλοπουλα",
        quantity=10.0,
        unit="piece",
        best_match=MatchedProductInfo(
            product_id=prod1.id,
            sku=prod1.sku,
            description=prod1.description,
            unit="piece"
        ),
        confidence=ConfidenceResult(score=0.98, decision=MatchDecision.AUTO_ACCEPT)
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="10 τεμ γαλοπουλα",
        lines=[line_match]
    )
    line_id = order.lines[0].id

    # Approve order
    OrderWorkflowService.approve_order(db=db_session, order_id=order.id)
    assert order.status == OrderStatus.APPROVED.value

    # 1. confirm_line must fail
    with pytest.raises(ValueError, match="is 'approved' and its lines cannot be modified"):
        OrderWorkflowService.confirm_line(db=db_session, order_id=order.id, line_id=line_id)

    # 2. correct_line must fail
    with pytest.raises(ValueError, match="is 'approved' and its lines cannot be modified"):
        OrderWorkflowService.correct_line(
            db=db_session, order_id=order.id, line_id=line_id, correct_product_id=prod2.id
        )

    # 3. update_line_final_values must fail
    with pytest.raises(ValueError, match="is 'approved' and its lines cannot be modified"):
        OrderWorkflowService.update_line_final_values(
            db=db_session, order_id=order.id, line_id=line_id, final_quantity=20.0
        )


def test_update_line_final_values_excludes_product_mutation(db_session):
    """
    Verify that update_line_final_values does NOT accept product mutations.
    Product corrections must go exclusively through correct_line().
    """
    import inspect
    sig = inspect.signature(OrderWorkflowService.update_line_final_values)
    assert "final_product_id" not in sig.parameters, "final_product_id must not be a parameter of update_line_final_values"

    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod1 = data["prod1"]

    line_match = LineMatchResult(
        line_number=1,
        original_text="10 τεμ γαλοπουλα",
        product_phrase="γαλοπουλα",
        quantity=10.0,
        unit="piece",
        best_match=MatchedProductInfo(
            product_id=prod1.id,
            sku=prod1.sku,
            description=prod1.description,
            unit="piece"
        ),
        confidence=ConfidenceResult(score=0.98, decision=MatchDecision.AUTO_ACCEPT)
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="10 τεμ γαλοπουλα",
        lines=[line_match]
    )
    line_id = order.lines[0].id

    # The operator can choose kilograms even when the catalog base unit is piece.
    kg_value = OrderWorkflowService.update_line_final_values(
        db=db_session, order_id=order.id, line_id=line_id, final_unit="kg"
    )
    assert kg_value.final_unit == "kg"
    updated = OrderWorkflowService.update_line_final_values(
        db=db_session,
        order_id=order.id,
        line_id=line_id,
        final_quantity=15.0,
        final_unit="piece"
    )
    assert updated.final_quantity == 15.0
    assert updated.final_unit == "piece"
    # Product remains unchanged
    assert updated.matched_product_id == prod1.id
    assert updated.final_sku == prod1.sku


def test_winning_match_candidate_persisted_as_rank_1(db_session):
    """
    Verify that create_order_from_match persists the winning candidate as rank 1,
    and alternatives follow at rank 2+, without duplicating the winning product.
    """
    data = setup_workflow_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod1 = data["prod1"]
    prod2 = data["prod2"]

    from backend.app.schemas.matching import MatchCandidateDto, MatchEvidence, MatchPriority

    line_match = LineMatchResult(
        line_number=1,
        original_text="10 τεμ γαλοπουλα",
        product_phrase="γαλοπουλα καπνιστη",
        quantity=10.0,
        unit="piece",
        best_match=MatchedProductInfo(
            product_id=prod1.id,
            sku=prod1.sku,
            description=prod1.description,
            unit="piece"
        ),
        confidence=ConfidenceResult(
            score=0.95,
            decision=MatchDecision.AUTO_ACCEPT,
            reasons=["+ Exact SKU match 'SKU-7843'", "+ Packaging matched"]
        ),
        alternatives=[
            # Candidate 2 (alternative)
            MatchCandidateDto(
                product_id=prod2.id,
                sku=prod2.sku,
                description=prod2.description,
                rank=2,
                score=0.72,
                match_priority=MatchPriority.FUZZY_DESCRIPTION,
                evidence=[MatchEvidence(evidence_type="fuzzy_description", score=0.72, detail="Fuzzy description match")]
            )
        ]
    )

    order = OrderWorkflowService.create_order_from_match(
        db=db_session,
        company_id=comp.id,
        customer_id=cust.id,
        raw_input="10 τεμ γαλοπουλα",
        lines=[line_match]
    )

    order_line = order.lines[0]
    candidates = order_line.candidates
    assert len(candidates) == 2

    # Rank 1: Winning best_match
    winner = next(c for c in candidates if c.rank == 1)
    assert winner.product_id == prod1.id
    assert winner.score == 0.95
    assert winner.match_type == "exact_sku"
    assert "+ Exact SKU match 'SKU-7843'" in winner.explanation

    # Rank 2: Alternative
    alt = next(c for c in candidates if c.rank == 2)
    assert alt.product_id == prod2.id
    assert alt.score == 0.72
    assert alt.match_type == "fuzzy_description"
