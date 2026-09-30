import csv
import hashlib
import io
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.app.config import settings
from backend.app.core.text_normalizer import is_quantity_grounded_in_span, is_unit_grounded_in_span
from backend.app.models.company import Company
from backend.app.models.business_settings import CompanyBusinessSettings
from backend.app.models.customer import Customer
from backend.app.models.product import Product, Packaging, ProductAlias
from backend.app.models.order import Order, OrderLine, MatchCandidate
from backend.app.models.memory import CustomerProductAlias, HumanCorrection
from backend.app.models.export import ExportProfile, ExportFieldMapping, ExportRecord
from backend.app.schemas.workflow import OrderStatus, OrderLineStatus
from backend.app.schemas.matching import LineMatchResult, MatchedProductInfo, ConfidenceResult, MatchDecision
from backend.app.schemas.export import ExportProfileCreate, ExportFieldMappingCreate
from backend.app.services.order_workflow_service import OrderWorkflowService, OrderApprovalError
from backend.app.services.order_parsing_service import OrderParsingService
from backend.app.services.matching_engine import MatchingEngine
from backend.app.services.export_engine import ExportEngine
from backend.app.services.export_profile_service import ExportProfileService, ExportProfileValidationError
from backend.app.services.learning_memory_service import LearningMemoryService
from backend.app.ai.base import BaseAIProvider
from backend.app.schemas.order import NormalizedOrderLineDraft


def setup_hardening_data(db_session: Session):
    company = Company(name="Hellas Food Services")
    db_session.add(company)
    db_session.flush()
    db_session.add(CompanyBusinessSettings(company_id=company.id, unitless_order_behavior="piece"))

    customer = Customer(
        company_id=company.id,
        customer_code="CUST-HARDEN-1",
        customer_name="Taverna Acropolis",
        email="info@demo-taverna.test",
        phone="0000000000"
    )
    db_session.add(customer)
    db_session.flush()

    prod_turkey = Product(
        company_id=company.id,
        sku="SKU-TURKEY-1",
        description="Γαλοπούλα Καπνιστή 1kg",
        unit="piece",
        barcode="5201111111111",
        active=True
    )
    prod_salami = Product(
        company_id=company.id,
        sku="SKU-SALAMI-2",
        description="Σαλάμι Μπύρας 300g",
        unit="piece",
        barcode="5202222222222",
        active=True
    )
    db_session.add_all([prod_turkey, prod_salami])
    db_session.flush()

    # Product alias: "καπνιστη" -> prod_turkey
    alias = ProductAlias(
        company_id=company.id,
        product_id=prod_turkey.id,
        original_phrase="καπνιστη",
        normalized_phrase="καπνιστη",
        active=True
    )
    db_session.add(alias)
    db_session.commit()

    return {
        "company": company,
        "customer": customer,
        "prod_turkey": prod_turkey,
        "prod_salami": prod_salami
    }


# =====================================================================
# 1. Server-Owned Match Persistence: Client-supplied match ignored
# =====================================================================
def test_create_from_match_ignores_client_forged_match(client: TestClient, db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_turkey = data["prod_turkey"]
    prod_salami = data["prod_salami"]

    # Client tries to forge matching: sends product_phrase "καπνιστη"
    # but claims it matched prod_salami with forged SKU, fake reasons, and 0.99 confidence
    payload = {
        "company_id": comp.id,
        "customer_id": cust.id,
        "text": "5 καπνιστη",
        "lines": [
            {
                "line_number": 1,
                "original_text": "5 καπνιστη",
                "product_phrase": "καπνιστη",
                "requested_quantity": 5.0,
                "requested_unit": "piece",
                "best_match": {
                    "product_id": prod_salami.id,
                    "sku": "FORGED-SALAMI-SKU",
                    "description": "Forged Salami",
                    "unit": "piece"
                },
                "confidence": {
                    "score": 0.99,
                    "decision": "auto_accept",
                    "reasons": ["Forged client assertion"]
                }
            }
        ]
    }

    resp = client.post("/api/v1/orders/create-from-match", json=payload)
    assert resp.status_code == 201
    res = resp.json()

    # The server must have re-evaluated the match against the database!
    # "καπνιστη" matches prod_turkey, NOT prod_salami
    order_line = res["lines"][0]
    assert order_line["matched_product_id"] == prod_turkey.id
    assert order_line["final_sku"] == prod_turkey.sku
    assert order_line["final_sku"] != "FORGED-SALAMI-SKU"


# =====================================================================
# 2. Idempotency Key Handling
# =====================================================================
def test_create_from_match_idempotency_key(client: TestClient, db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]

    payload = {
        "company_id": comp.id,
        "customer_id": cust.id,
        "text": "3 καπνιστη"
    }

    headers = {"Idempotency-Key": "UNIQUE-ORDER-IDEMP-001"}

    # First request
    resp1 = client.post("/api/v1/orders/create-from-match", json=payload, headers=headers)
    assert resp1.status_code == 201
    order1 = resp1.json()

    # Second request with the identical idempotency key
    resp2 = client.post("/api/v1/orders/create-from-match", json=payload, headers=headers)
    assert resp2.status_code in (200, 201)
    order2 = resp2.json()

    # Must return the same order
    assert order1["id"] == order2["id"]
    assert order1["order_number"] == order2["order_number"]

    # Verify only 1 order exists in database
    orders = db_session.execute(
        select(Order).where(Order.company_id == comp.id, Order.idempotency_key == "UNIQUE-ORDER-IDEMP-001")
    ).scalars().all()
    assert len(orders) == 1

    conflict = client.post(
        "/api/v1/orders/create-from-match",
        json={**payload, "text": "4 καπνιστη"}, headers=headers,
    )
    assert conflict.status_code == 409
    assert db_session.execute(select(Order).where(Order.company_id == comp.id)).scalars().all() == orders


# =====================================================================
# 3. Input Size & Line Limits (100k bytes & 500 lines)
# =====================================================================
def test_create_from_match_size_and_line_limits(client: TestClient, db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]

    # 1. Text payload exceeds MAX_RAW_ORDER_TEXT_SIZE (100,000 bytes) -> 413
    oversized_text = "καπνιστη " * 12000  # ~108,000 bytes
    assert len(oversized_text.encode("utf-8")) > settings.MAX_RAW_ORDER_TEXT_SIZE

    payload_large = {
        "company_id": comp.id,
        "customer_id": cust.id,
        "text": oversized_text
    }
    resp = client.post("/api/v1/orders/create-from-match", json=payload_large)
    assert resp.status_code == 413
    assert "exceeds maximum allowed size" in resp.json()["detail"]

    # 2. Lines array exceeds MAX_ORDER_LINES (500 lines) -> 400
    excessive_lines = [
        {
            "line_number": i,
            "original_text": f"{i} καπνιστη",
            "product_phrase": "καπνιστη",
            "requested_quantity": 1.0,
            "requested_unit": "piece"
        }
        for i in range(1, 502)
    ]
    payload_many_lines = {
        "company_id": comp.id,
        "customer_id": cust.id,
        "lines": excessive_lines
    }
    resp_lines = client.post("/api/v1/orders/create-from-match", json=payload_many_lines)
    assert resp_lines.status_code == 400
    assert "exceed maximum limit" in resp_lines.json()["detail"]


# =====================================================================
# 4. Deterministic Grounding Checks for Quantity and Unit
# =====================================================================
def test_deterministic_grounding_quantity_and_unit():
    # Grounding quantity tests: is_quantity_grounded_in_span(quantity, text_span, raw_input)
    assert is_quantity_grounded_in_span(5.0, "5 κιλα φετα", "5 κιλα φετα") is True
    assert is_quantity_grounded_in_span(5.0, "πεντε κιλα φετα", "πεντε κιλα φετα") is True
    assert is_quantity_grounded_in_span(100.0, "5 κιλα φετα", "5 κιλα φετα") is False

    assert is_quantity_grounded_in_span(2.5, "2,5 κιλά SKU-100", "2,5 κιλά SKU-100", "SKU-100")
    assert not is_quantity_grounded_in_span(100.0, "2 τεμάχια SKU-100", "2 τεμάχια SKU-100", "SKU-100")
    assert not is_quantity_grounded_in_span(2.0, "2 κιβώτια 12 τεμάχια SKU-100", "2 κιβώτια 12 τεμάχια SKU-100", "SKU-100")
    row = "180406 | ΠΑΡΙΖΑ 3.0 ΚΙΛ | ΚΙΛ | 35"
    assert is_quantity_grounded_in_span(35, row, row, "180406", "35")
    assert not is_quantity_grounded_in_span(3, row, row, "180406", "35")
    assert not is_quantity_grounded_in_span(10, "10+1", "10+1", bonus_quantity=1)
    assert is_quantity_grounded_in_span(10, "10KIB+1KIB", "10KIB+1KIB", quantity_text="10KIB+1KIB", bonus_quantity=1)
    assert not is_quantity_grounded_in_span(10, "10+100", "10+100", quantity_text="10+1", bonus_quantity=1)
    assert is_unit_grounded_in_span("unknown", None, False, row, row, "180406", "35")
    assert not is_unit_grounded_in_span("kg", "ΚΙΛ", True, row, row, "180406", "35")

    # Default quantity 1.0 is grounded when no explicit number is present
    assert is_quantity_grounded_in_span(1.0, "γαλοπουλα καπνιστη", "γαλοπουλα καπνιστη") is True
    # But 1.0 is NOT grounded if text mentions a conflicting number
    assert is_quantity_grounded_in_span(1.0, "5 γαλοπουλα", "5 γαλοπουλα") is False

    # Unit grounding tests: is_unit_grounded_in_span(unit, raw_unit, unit_explicit, text_span, raw_input)
    assert is_unit_grounded_in_span("kg", "κιλα", True, "5 κιλα φετα", "5 κιλα φετα") is True
    assert is_unit_grounded_in_span("case", "κιβωτια", True, "2 κιβωτια μπυρες", "2 κιβωτια μπυρες") is True
    assert is_unit_grounded_in_span("piece", "τεμαχιο", True, "1 τεμαχιο τυρι", "1 τεμαχιο τυρι") is True
    # Default piece is grounded if no unit mentioned
    assert is_unit_grounded_in_span("unknown", None, False, "5 φετα", "5 φετα") is True
    # Contradicted unit: AI extracted raw_unit='κιλα' (kg) when text only says 'κιβωτια' (case)
    assert is_unit_grounded_in_span("kg", "κιλα", True, "2 κιβωτια μπυρες", "2 κιβωτια μπυρες") is False


@pytest.mark.asyncio
async def test_order_parsing_rejects_hallucinated_quantity(db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]

    class HallucinatingAIProvider(BaseAIProvider):
        name: str = "hallucinator"

        async def extract_order(self, normalized_input, context=None):
            return [
                NormalizedOrderLineDraft(
                    original_text="1 καπνιστη",
                    product_phrase="καπνιστη",
                    quantity=999.0,  # Hallucinated! Text clearly has 1
                    unit="piece",
                    raw_unit=None,
                    unit_explicit=False
                )
            ]

    service = OrderParsingService(ai_provider=HallucinatingAIProvider())

    with pytest.raises(ValueError, match="cannot be grounded"):
        await service.parse_order(
            db=db_session,
            company_id=comp.id,
            customer_id=cust.id,
            text="1 καπνιστη"
        )


# =====================================================================
# 5. Transaction Atomicity & Rollback in Confirm/Correct
# =====================================================================
def test_confirm_and_correct_atomicity_and_rollback(db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_turkey = data["prod_turkey"]
    prod_salami = data["prod_salami"]

    order = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_number="ORD-TX-TEST",
        raw_input="1 καπνιστη"
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="1 καπνιστη",
        product_phrase="καπνιστη",
        requested_quantity=1.0,
        requested_unit="piece",
        status=OrderLineStatus.NEEDS_REVIEW.value
    )
    db_session.add(line)
    db_session.commit()

    # Simulate an error inside correct_line during line status change
    # by passing an invalid correct_product_id
    with pytest.raises(ValueError, match="does not exist"):
        OrderWorkflowService.correct_line(
            db=db_session,
            order_id=order.id,
            line_id=line.id,
            correct_product_id=999999
        )

    # Verify no HumanCorrection or alias modification was committed!
    db_session.expire_all()
    corrections = db_session.execute(
        select(HumanCorrection).where(HumanCorrection.order_id == order.id)
    ).scalars().all()
    assert len(corrections) == 0

    reloaded_line = db_session.get(OrderLine, line.id)
    assert reloaded_line.status == OrderLineStatus.NEEDS_REVIEW.value


# =====================================================================
# 6. Centralized Lifecycle State Machine
# =====================================================================
def test_centralized_lifecycle_state_machine(db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_turkey = data["prod_turkey"]

    order = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_number="ORD-STATE-1",
        raw_input="2 καπνιστη",
        status=OrderStatus.PENDING_REVIEW.value
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="2 καπνιστη",
        product_phrase="καπνιστη",
        requested_quantity=2.0,
        requested_unit="piece",
        matched_product_id=prod_turkey.id,
        status=OrderLineStatus.NEEDS_REVIEW.value
    )
    db_session.add(line)
    db_session.commit()

    # 1. Cannot approve order when lines are still pending review
    with pytest.raises(OrderApprovalError, match="require review"):
        OrderWorkflowService.approve_order(db=db_session, order_id=order.id)

    # Confirm line
    OrderWorkflowService.confirm_line(db=db_session, order_id=order.id, line_id=line.id)

    # 2. Valid transition: pending_review -> approved
    approved_order = OrderWorkflowService.approve_order(db=db_session, order_id=order.id)
    assert approved_order.status == OrderStatus.APPROVED.value
    assert approved_order.approved_snapshot is not None

    # 3. Idempotent approval
    approved_again = OrderWorkflowService.approve_order(db=db_session, order_id=order.id)
    assert approved_again.status == OrderStatus.APPROVED.value

    # 4. Valid transition: approved -> exported via ExportEngine
    profile = ExportProfile(
        company_id=comp.id,
        name="Lifecycle Export Profile",
        format="json",
        encoding="utf-8"
    )
    db_session.add(profile)
    db_session.flush()
    mapping = ExportFieldMapping(
        export_profile_id=profile.id,
        source_field="order.order_number",
        output_column_name="order_num",
        column_order=1
    )
    db_session.add(mapping)
    db_session.commit()

    ExportEngine.export_order(db=db_session, order_id=order.id, profile_id=profile.id, preview=False)
    db_session.refresh(order)
    assert order.status == OrderStatus.EXPORTED.value

    # 5. Invalid transition: cannot cancel exported order
    with pytest.raises(ValueError, match="cannot be cancelled because its status is 'exported'"):
        OrderWorkflowService.cancel_order(db=db_session, order_id=order.id)

    # 6. Invalid transition: cannot approve exported order
    with pytest.raises(ValueError, match="cannot be approved because its status is 'exported'"):
        OrderWorkflowService.approve_order(db=db_session, order_id=order.id)

    # 7. Test cancelled order transitions
    order2 = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_number="ORD-STATE-CANCEL",
        raw_input="cancel test",
        status=OrderStatus.PENDING_REVIEW.value
    )
    db_session.add(order2)
    db_session.commit()

    OrderWorkflowService.cancel_order(db=db_session, order_id=order2.id)
    db_session.refresh(order2)
    assert order2.status == OrderStatus.CANCELLED.value

    # Cannot cancel already cancelled order
    with pytest.raises(ValueError, match="cannot be cancelled because its status is 'cancelled'"):
        OrderWorkflowService.cancel_order(db=db_session, order_id=order2.id)

    # Cannot approve cancelled order
    with pytest.raises(ValueError, match="cannot be approved because its status is 'cancelled'"):
        OrderWorkflowService.approve_order(db=db_session, order_id=order2.id)


# =====================================================================
# 7. Approved Order Immutability
# =====================================================================
def test_approved_order_is_immutable(db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_turkey = data["prod_turkey"]
    prod_salami = data["prod_salami"]

    order = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_number="ORD-IMMUT-1",
        raw_input="1 καπνιστη",
        status=OrderStatus.PENDING_REVIEW.value
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="1 καπνιστη",
        product_phrase="καπνιστη",
        requested_quantity=1.0,
        requested_unit="piece",
        matched_product_id=prod_turkey.id,
        status=OrderLineStatus.AUTO_ACCEPTED.value
    )
    db_session.add(line)
    db_session.commit()

    OrderWorkflowService.approve_order(db=db_session, order_id=order.id)

    # Any modification attempts on approved order must raise ValueError
    with pytest.raises(ValueError, match="cannot be modified"):
        OrderWorkflowService.confirm_line(db=db_session, order_id=order.id, line_id=line.id)

    with pytest.raises(ValueError, match="cannot be modified"):
        OrderWorkflowService.correct_line(db=db_session, order_id=order.id, line_id=line.id, correct_product_id=prod_salami.id)

    with pytest.raises(ValueError, match="cannot be modified"):
        OrderWorkflowService.update_line_final_values(db=db_session, order_id=order.id, line_id=line.id, final_quantity=5.0)


# =====================================================================
# 8. Approved Snapshot Immutability against Master Catalog Mutation
# =====================================================================
def test_approved_snapshot_preserves_historical_data_when_catalog_mutates(db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_turkey = data["prod_turkey"]

    order = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_number="ORD-SNAP-1",
        raw_input="10 καπνιστη",
        status=OrderStatus.PENDING_REVIEW.value
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="10 καπνιστη",
        product_phrase="καπνιστη",
        requested_quantity=10.0,
        requested_unit="piece",
        matched_product_id=prod_turkey.id,
        final_sku=prod_turkey.sku,
        final_quantity=10.0,
        final_unit="piece",
        status=OrderLineStatus.AUTO_ACCEPTED.value
    )
    db_session.add(line)
    db_session.commit()

    # Approve order to generate approved_snapshot
    OrderWorkflowService.approve_order(db=db_session, order_id=order.id)

    # Now mutate the catalog product
    prod_turkey.sku = "NEW-CHANGED-SKU-999"
    prod_turkey.description = "New Changed Description"
    db_session.commit()

    # get_canonical_order must still return the snapshot's original SKU and description
    canonical = OrderWorkflowService.get_canonical_order(order=order)
    assert canonical.items[0].sku == "SKU-TURKEY-1"
    assert canonical.items[0].description == "Γαλοπούλα Καπνιστή 1kg"


# =====================================================================
# 9. Packaging Unit Matching & Ambiguity Rejection
# =====================================================================
def test_packaging_unit_matching_and_ambiguity(db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_turkey = data["prod_turkey"]

    # Create a packaging for case: 12 pieces/case
    pkg1 = Packaging(
        product_id=prod_turkey.id,
        package_code="BOX-12",
        package_type="box",
        pieces_per_case=12.0,
        unit="case"
    )
    db_session.add(pkg1)
    db_session.commit()

    order = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_number="ORD-PKG-1",
        raw_input="2 κιβωτια καπνιστη",
        status=OrderStatus.PENDING_REVIEW.value
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="2 κιβωτια καπνιστη",
        product_phrase="καπνιστη",
        requested_quantity=2.0,
        requested_unit="case",
        matched_product_id=prod_turkey.id,
        status=OrderLineStatus.NEEDS_REVIEW.value
    )
    db_session.add(line)
    db_session.commit()

    # 1. Successfully matches packaging when unambiguous
    updated_line = OrderWorkflowService.update_line_final_values(
        db=db_session,
        order_id=order.id,
        line_id=line.id,
        final_unit="case"
    )
    assert updated_line.matched_packaging_id == pkg1.id
    assert updated_line.final_unit == "case"

    # 2. Add a second packaging for 'case' with different ratio (ambiguity!)
    pkg2 = Packaging(
        product_id=prod_turkey.id,
        package_code="BOX-24",
        package_type="big_box",
        pieces_per_case=24.0,
        unit="case"
    )
    db_session.add(pkg2)
    db_session.commit()
    db_session.expire_all()

    with pytest.raises(ValueError, match="Ambiguous packaging"):
        OrderWorkflowService.update_line_final_values(
            db=db_session,
            order_id=order.id,
            line_id=line.id,
            final_unit="case"
        )

    # 3. Unsupported unit
    with pytest.raises(ValueError, match="Unknown or invalid unit 'barrels'"):
        OrderWorkflowService.update_line_final_values(
            db=db_session,
            order_id=order.id,
            line_id=line.id,
            final_unit="barrels"
        )


def test_initial_matching_resolves_package_code_and_reviews_ambiguous_unit(db_session: Session):
    data = setup_hardening_data(db_session)
    product = data["prod_turkey"]
    first = Packaging(product_id=product.id, package_code="BOX-12", package_type="box",
                      pieces_per_case=12, unit="case")
    db_session.add(first)
    db_session.commit()

    matched = MatchingEngine.match_line(
        db_session, data["company"].id, data["customer"].id, 1,
        "2 BOX-12", "BOX-12", 2, "piece", unit_explicit=False,
    )
    assert matched.best_match.product_id == product.id
    assert matched.matched_packaging_id == first.id
    assert matched.final_unit == "case"

    db_session.add(Packaging(product_id=product.id, package_code="BOX-24", package_type="box",
                             pieces_per_case=24, unit="case"))
    db_session.commit()
    db_session.expire_all()
    exact = MatchingEngine.match_line(
        db_session, data["company"].id, data["customer"].id, 1,
        "2 BOX-12", "BOX-12", 2, "piece", unit_explicit=False,
    )
    assert exact.matched_packaging_id == first.id
    exact_order = OrderWorkflowService.create_order_from_match(
        db_session, data["company"].id, data["customer"].id, "2 BOX-12", [exact],
    )
    OrderWorkflowService.approve_order(db_session, exact_order.id)

    ambiguous = MatchingEngine.match_line(
        db_session, data["company"].id, data["customer"].id, 1,
        "2 κιβώτια καπνιστη", "καπνιστη", 2, "case", raw_unit="κιβώτια", unit_explicit=True,
    )
    assert ambiguous.confidence.decision == MatchDecision.NEEDS_REVIEW
    assert ambiguous.matched_packaging_id is None


def test_product_correction_preserves_requested_case_unit(db_session: Session):
    data = setup_hardening_data(db_session)
    salami = data["prod_salami"]
    packaging = Packaging(product_id=salami.id, package_type="case", unit="case", pieces_per_case=12)
    db_session.add(packaging)
    db_session.commit()
    line_result = LineMatchResult(
        line_number=1, original_text="2 κιβώτια σαλάμι", product_phrase="σαλάμι",
        quantity=2, unit="case", raw_unit="κιβώτια", unit_explicit=True,
        best_match=MatchedProductInfo(product_id=data["prod_turkey"].id,
                                      sku=data["prod_turkey"].sku,
                                      description=data["prod_turkey"].description,
                                      unit="piece"),
        confidence=ConfidenceResult(score=0.5, decision=MatchDecision.NEEDS_REVIEW),
    )
    order = OrderWorkflowService.create_order_from_match(
        db_session, data["company"].id, data["customer"].id,
        "2 κιβώτια σαλάμι", [line_result],
    )
    _, corrected = OrderWorkflowService.correct_line(db_session, order.id, order.lines[0].id, salami.id)
    assert corrected.final_unit == "case"
    assert corrected.matched_packaging_id == packaging.id
    assert corrected.status == OrderLineStatus.CORRECTED.value


# =====================================================================
# 10. Formula Injection Escaping: CSV/XLSX Escaped, JSON Untouched
# =====================================================================
def test_formula_injection_escaping_distinction(db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_turkey = data["prod_turkey"]

    order = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_number="ORD-FORMULA-1",
        raw_input="Formula Test",
        status=OrderStatus.PENDING_REVIEW.value
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="=SUM(A1:A10)",
        product_phrase="+306912345678",
        requested_quantity=1.0,
        requested_unit="piece",
        matched_product_id=prod_turkey.id,
        final_sku="-SKU-FORMULA",
        final_quantity=1.0,
        final_unit="piece",
        status=OrderLineStatus.AUTO_ACCEPTED.value
    )
    db_session.add(line)
    db_session.commit()

    OrderWorkflowService.approve_order(db=db_session, order_id=order.id)

    # Profile for CSV
    profile_csv = ExportProfile(
        company_id=comp.id,
        name="CSV Formula Test",
        format="csv",
        encoding="utf-8"
    )
    db_session.add(profile_csv)
    db_session.flush()
    mapping_csv = ExportFieldMapping(
        export_profile_id=profile_csv.id,
        source_field="line.product_phrase",
        output_column_name="Phrase",
        column_order=1
    )
    mapping_csv2 = ExportFieldMapping(
        export_profile_id=profile_csv.id,
        source_field="line.sku",
        output_column_name="SKU",
        column_order=2
    )
    db_session.add_all([mapping_csv, mapping_csv2])

    # Profile for JSON
    profile_json = ExportProfile(
        company_id=comp.id,
        name="JSON Formula Test",
        format="json",
        encoding="utf-8"
    )
    db_session.add(profile_json)
    db_session.flush()
    mapping_json = ExportFieldMapping(
        export_profile_id=profile_json.id,
        source_field="line.product_phrase",
        output_column_name="phrase",
        column_order=1
    )
    db_session.add(mapping_json)
    db_session.commit()

    # 1. CSV export should escape '+' and '-' with single quote "'"
    res_csv_bytes, media_type, filename = ExportEngine.export_order(
        db=db_session, order_id=order.id, profile_id=profile_csv.id, preview=True
    )
    csv_text = res_csv_bytes.decode("utf-8")
    assert "'+306912345678" in csv_text
    assert "'-SKU-FORMULA" in csv_text

    # 2. JSON export must NOT escape '+' (untouched clean JSON)
    res_json_bytes, media_type, filename = ExportEngine.export_order(
        db=db_session, order_id=order.id, profile_id=profile_json.id, preview=True
    )
    json_data = json.loads(res_json_bytes.decode("utf-8"))
    assert json_data[0]["phrase"] == "+306912345678"
    assert not json_data[0]["phrase"].startswith("'")


# =====================================================================
# 11. ExportRecord Audit Tracking and Content Hashing
# =====================================================================
def test_export_record_audit_and_content_hash(db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_turkey = data["prod_turkey"]

    order = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_number="ORD-AUDIT-1",
        raw_input="Audit Test",
        status=OrderStatus.PENDING_REVIEW.value
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="1 καπνιστη",
        product_phrase="καπνιστη",
        requested_quantity=1.0,
        requested_unit="piece",
        matched_product_id=prod_turkey.id,
        status=OrderLineStatus.AUTO_ACCEPTED.value
    )
    db_session.add(line)
    db_session.commit()

    OrderWorkflowService.approve_order(db=db_session, order_id=order.id)

    profile = ExportProfile(
        company_id=comp.id,
        name="Audit Profile",
        format="json",
        encoding="utf-8"
    )
    db_session.add(profile)
    db_session.flush()
    mapping = ExportFieldMapping(
        export_profile_id=profile.id,
        source_field="order.order_number",
        output_column_name="order_num",
        column_order=1
    )
    db_session.add(mapping)
    db_session.commit()

    # Non-preview export writes to ExportRecord
    res_bytes, media_type, filename = ExportEngine.export_order(
        db=db_session, order_id=order.id, profile_id=profile.id, preview=False
    )
    expected_hash = hashlib.sha256(res_bytes).hexdigest()

    records = db_session.execute(
        select(ExportRecord).where(ExportRecord.order_id == order.id)
    ).scalars().all()
    assert len(records) == 1
    rec = records[0]
    assert rec.content_hash == expected_hash
    assert rec.format == "json"
    assert rec.filename == filename


# =====================================================================
# 12. Export Profile Validation: Duplicate Columns and Encoding
# =====================================================================
def test_export_profile_validation(db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]

    # 1. Duplicate output_column_name rejected
    with pytest.raises(ExportProfileValidationError, match="Duplicate output_column_name 'SKU'"):
        ExportProfileService.validate_profile_mappings([
            ExportFieldMappingCreate(source_field="line.sku", output_column_name="SKU", column_order=1),
            ExportFieldMappingCreate(source_field="line.description", output_column_name="SKU", column_order=2)
        ])

    # 2. Unsupported encoding rejected
    with pytest.raises(ExportProfileValidationError, match="Unsupported encoding 'invalid-enc-123'"):
        ExportProfileService.create_profile(
            db=db_session,
            payload=ExportProfileCreate(
                company_id=comp.id,
                name="Bad Encoding Profile",
                format="csv",
                encoding="invalid-enc-123",
                mappings=[
                    ExportFieldMappingCreate(source_field="line.sku", output_column_name="SKU", column_order=1)
                ]
            )
        )

    # 3. Whitelisted encodings accepted
    for enc in ["utf-8", "utf-8-sig", "windows-1253", "iso-8859-7", "latin1", "ascii"]:
        p = ExportProfileService.create_profile(
            db=db_session,
            payload=ExportProfileCreate(
                company_id=comp.id,
                name=f"Profile {enc}",
                format="csv",
                encoding=enc,
                mappings=[
                    ExportFieldMappingCreate(source_field="line.sku", output_column_name="SKU", column_order=1)
                ]
            )
        )
        assert p.encoding == enc


# =====================================================================
# 13. Path-vs-Payload Identity Validation in API
# =====================================================================
def test_path_vs_payload_identity_validation_in_api(client: TestClient, db_session: Session):
    data = setup_hardening_data(db_session)
    comp = data["company"]
    cust = data["customer"]
    prod_turkey = data["prod_turkey"]
    prod_salami = data["prod_salami"]

    order = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_number="ORD-PATH-1",
        raw_input="1 καπνιστη"
    )
    db_session.add(order)
    db_session.flush()

    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="1 καπνιστη",
        product_phrase="καπνιστη",
        requested_quantity=1.0,
        requested_unit="piece",
        matched_product_id=prod_salami.id
    )
    db_session.add(line)
    db_session.commit()

    base_url = f"/api/v1/orders/{order.id}/lines/{line.id}/correct"

    # 1. Payload order_id mismatch
    p1 = {
        "customer_id": cust.id,
        "order_id": order.id + 999,
        "line_id": line.id,
        "correct_product_id": prod_turkey.id,
        "suggested_product_id": prod_salami.id,
        "original_phrase": "καπνιστη"
    }
    r1 = client.post(base_url, json=p1)
    assert r1.status_code == 400
    assert "order_id in payload does not match path" in r1.json()["detail"]

    # 2. Payload line_id mismatch
    p2 = {
        "customer_id": cust.id,
        "order_id": order.id,
        "line_id": line.id + 999,
        "correct_product_id": prod_turkey.id,
        "suggested_product_id": prod_salami.id,
        "original_phrase": "καπνιστη"
    }
    r2 = client.post(base_url, json=p2)
    assert r2.status_code == 400
    assert "line_id in payload does not match path" in r2.json()["detail"]

    # 3. Payload customer_id mismatch
    p3 = {
        "customer_id": cust.id + 999,
        "order_id": order.id,
        "line_id": line.id,
        "correct_product_id": prod_turkey.id,
        "suggested_product_id": prod_salami.id,
        "original_phrase": "καπνιστη"
    }
    r3 = client.post(base_url, json=p3)
    assert r3.status_code == 400
    assert "customer_id in payload does not match order's customer" in r3.json()["detail"]

    # 4. Payload suggested_product_id mismatch
    p4 = {
        "customer_id": cust.id,
        "order_id": order.id,
        "line_id": line.id,
        "correct_product_id": prod_turkey.id,
        "suggested_product_id": prod_turkey.id,  # But line.matched_product_id is prod_salami.id!
        "original_phrase": "καπνιστη"
    }
    r4 = client.post(base_url, json=p4)
    assert r4.status_code == 400
    assert "suggested_product_id in payload does not match" in r4.json()["detail"]


# =====================================================================
# 14. Multi-Tenant Foreign Key Isolation in SQL
# =====================================================================
def test_multi_tenant_foreign_key_isolation(db_session: Session):
    company_a = Company(name="Company A")
    company_b = Company(name="Company B")
    db_session.add_all([company_a, company_b])
    db_session.flush()

    customer_a = Customer(company_id=company_a.id, customer_code="CUST-A", customer_name="Customer A")
    customer_b = Customer(company_id=company_b.id, customer_code="CUST-B", customer_name="Customer B")
    prod_a = Product(company_id=company_a.id, sku="SKU-A", description="Product A", unit="piece", active=True)
    db_session.add_all([customer_a, customer_b, prod_a])
    db_session.commit()

    # 1. Attempting to create an Order for Company A referencing Customer B from Company B
    # Foreign key constraint fk_order_customer_company enforces (customer_id, company_id) -> customers(id, company_id)
    with pytest.raises(IntegrityError):
        order_cross = Order(
            company_id=company_a.id,
            customer_id=customer_b.id,
            order_number="ORD-CROSS-1",
            raw_input="Cross company order"
        )
        db_session.add(order_cross)
        db_session.commit()
    db_session.rollback()

    # ProductAlias must also stay within its company.
    with pytest.raises(IntegrityError):
        db_session.add(ProductAlias(
            company_id=company_b.id, product_id=prod_a.id,
            original_phrase="cross alias", normalized_phrase="cross alias", active=True
        ))
        db_session.commit()
    db_session.rollback()


def test_tenant_constraints_cover_child_business_references(db_session: Session):
    company_a = Company(name="Tenant A")
    company_b = Company(name="Tenant B")
    db_session.add_all([company_a, company_b])
    db_session.flush()
    customer_b = Customer(company_id=company_b.id, customer_code="B", customer_name="Buyer B")
    product_a = Product(company_id=company_a.id, sku="A", description="Product A", unit="piece")
    product_b = Product(company_id=company_b.id, sku="B", description="Product B", unit="piece")
    profile_a = ExportProfile(company_id=company_a.id, name="Profile A", format="json")
    db_session.add_all([customer_b, product_a, product_b, profile_a])
    db_session.flush()
    order_b = Order(company_id=company_b.id, customer_id=customer_b.id, order_number="B-1", raw_input="one")
    db_session.add(order_b)
    db_session.flush()
    line_b = OrderLine(order_id=order_b.id, company_id=company_b.id, line_number=1,
                       original_text="one", product_phrase="one", requested_quantity=1,
                       requested_unit="piece", matched_product_id=product_b.id)
    db_session.add(line_b)
    db_session.commit()

    invalid_rows = [
        Packaging(company_id=company_b.id, product_id=product_a.id, package_type="case", pieces_per_case=12),
        CustomerProductAlias(company_id=company_b.id, customer_id=customer_b.id,
                             product_id=product_a.id, original_phrase="wrong", normalized_phrase="wrong"),
        OrderLine(company_id=company_b.id, order_id=order_b.id, line_number=2,
                  original_text="wrong", product_phrase="wrong", requested_quantity=1,
                  requested_unit="piece", matched_product_id=product_a.id),
        MatchCandidate(company_id=company_b.id, order_line_id=line_b.id, product_id=product_a.id,
                       rank=1, match_type="exact_sku", score=1, explanation="wrong"),
        HumanCorrection(company_id=company_b.id, customer_id=customer_b.id,
                        correct_product_id=product_a.id, original_phrase="wrong"),
        ExportRecord(company_id=company_b.id, order_id=order_b.id, export_profile_id=profile_a.id,
                     format="json", filename="wrong.json"),
    ]
    for row in invalid_rows:
        with pytest.raises(IntegrityError):
            db_session.add(row)
            db_session.commit()
        db_session.rollback()

    order_b.last_export_profile_id = profile_a.id
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_order_version_rejects_stale_operator_write(db_session: Session, test_engine):
    data = setup_hardening_data(db_session)
    order = Order(company_id=data["company"].id, customer_id=data["customer"].id,
                  order_number="VERSION-1", raw_input="one")
    db_session.add(order)
    db_session.commit()

    first = Session(test_engine)
    second = Session(test_engine)
    try:
        first_order = first.get(Order, order.id)
        second_order = second.get(Order, order.id)
        first_order.version += 1
        first_order.status = OrderStatus.PENDING_REVIEW.value
        first.commit()
        second_order.version += 1
        second_order.status = OrderStatus.CANCELLED.value
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()
        db_session.expire_all()
        assert db_session.get(Order, order.id).status == OrderStatus.PENDING_REVIEW.value
    finally:
        first.close()
        second.close()
