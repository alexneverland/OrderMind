import pytest
from sqlalchemy.orm import Session

from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.product import Product, ProductAlias, Packaging
from backend.app.models.memory import CustomerProductAlias
from backend.app.services.matching_engine import MatchingEngine
from backend.app.schemas.matching import MatchDecision


def setup_catalog(db_session: Session):
    company = Company(name="Hellas Food Supplies")
    db_session.add(company)
    db_session.flush()

    customer_a = Customer(company_id=company.id, customer_code="CUST-A", customer_name="Super Market Alfa")
    customer_b = Customer(company_id=company.id, customer_code="CUST-B", customer_name="Deli Beta")
    db_session.add_all([customer_a, customer_b])
    db_session.flush()

    prod1 = Product(
        company_id=company.id,
        sku="18452",
        description="Ζαμπόν Μπούτι Βραστό 500g",
        barcode="5201234567890",
        unit="piece",
        active=True
    )
    prod2 = Product(
        company_id=company.id,
        sku="7843",
        description="Γαλοπούλα Καπνιστή 1kg",
        barcode="5209876543210",
        unit="piece",
        active=True
    )
    prod3 = Product(
        company_id=company.id,
        sku="9999",
        description="Σαλάμι Αέρος 250g",
        barcode="5205555555555",
        unit="piece",
        active=True
    )
    db_session.add_all([prod1, prod2, prod3])
    db_session.flush()

    # Packaging for prod1: case of 12 pieces
    pkg1 = Packaging(
        product_id=prod1.id,
        package_type="case",
        pieces_per_case=12.0
    )

    db_session.add(pkg1)

    # Global alias for prod1
    g_alias = ProductAlias(
        company_id=company.id,
        product_id=prod1.id,
        original_phrase="μικρο ζαμπον",
        normalized_phrase="μικρο ζαμπον",
        active=True
    )
    db_session.add(g_alias)

    # Customer aliases: Customer A calls "κοκκινο" -> prod2 (7843), Customer B calls "κοκκινο" -> prod3 (9999)
    ca_a = CustomerProductAlias(
        customer_id=customer_a.id,
        product_id=prod2.id,
        original_phrase="κοκκινο",
        normalized_phrase="κοκκινο",
        confirmed_count=8,
        active=True
    )
    ca_b = CustomerProductAlias(
        customer_id=customer_b.id,
        product_id=prod3.id,
        original_phrase="κοκκινο",
        normalized_phrase="κοκκινο",
        confirmed_count=2,
        active=True
    )
    db_session.add_all([ca_a, ca_b])
    db_session.commit()

    return {
        "company": company,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "prod1": prod1,
        "prod2": prod2,
        "prod3": prod3,
    }


def test_exact_sku_match(db_session):
    data = setup_catalog(db_session)
    res = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_a"].id,
        line_number=1,
        original_text="5 18452",
        product_phrase="18452",
        quantity=5.0,
        unit="piece"
    )
    assert res.best_match is not None
    assert res.best_match.sku == "18452"
    assert res.best_match.product_id == data["prod1"].id
    assert res.confidence.decision == MatchDecision.AUTO_ACCEPT
    assert res.confidence.score >= 0.95
    assert any("Exact SKU match" in r for r in res.confidence.reasons)


def test_exact_barcode_match(db_session):
    data = setup_catalog(db_session)
    res = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_a"].id,
        line_number=1,
        original_text="5201234567890 2",
        product_phrase="5201234567890",
        quantity=2.0,
        unit="piece"
    )
    assert res.best_match is not None
    assert res.best_match.barcode == "5201234567890"
    assert res.best_match.sku == "18452"
    assert res.confidence.decision == MatchDecision.AUTO_ACCEPT
    assert any("Exact Barcode match" in r for r in res.confidence.reasons)


def test_customer_alias_isolation(db_session):
    """
    Customer A orders 'κοκκινο' -> SKU 7843 (confirmed 8 times -> auto_accept).
    Customer B orders 'κοκκινο' -> SKU 9999 (confirmed 2 times -> needs_review).
    No cross-customer leakage.
    """
    data = setup_catalog(db_session)

    res_a = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_a"].id,
        line_number=1,
        original_text="10 κοκκινα",
        product_phrase="κοκκινα",
        quantity=10.0,
        unit="piece"
    )
    assert res_a.best_match is not None
    assert res_a.best_match.sku == "7843"
    assert res_a.confidence.decision == MatchDecision.AUTO_ACCEPT
    assert res_a.confidence.score == 0.97
    assert any("Customer alias 'κοκκινο' matched" in r for r in res_a.confidence.reasons)

    res_b = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_b"].id,
        line_number=1,
        original_text="5 κοκκινο",
        product_phrase="κοκκινο",
        quantity=5.0,
        unit="piece"
    )
    assert res_b.best_match is not None
    assert res_b.best_match.sku == "9999"
    assert res_b.best_match.sku != "7843"
    # Base 0.90 + bonus (2-1)*0.01 = 0.91 -> needs_review
    assert res_b.confidence.score == 0.91
    assert res_b.confidence.decision == MatchDecision.NEEDS_REVIEW


def test_global_alias_match(db_session):
    data = setup_catalog(db_session)
    res = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_a"].id,
        line_number=1,
        original_text="3 μικρο ζαμπον",
        product_phrase="μικρο ζαμπον",
        quantity=3.0,
        unit="piece"
    )
    assert res.best_match is not None
    assert res.best_match.sku == "18452"
    assert any("Global company alias 'μικρο ζαμπον' matched" in r for r in res.confidence.reasons)


def test_exact_normalized_description_match(db_session):
    data = setup_catalog(db_session)
    # Different case and stripped accents
    res = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_a"].id,
        line_number=1,
        original_text="1 ΖΑΜΠΟΝ ΜΠΟΥΤΙ ΒΡΑΣΤΟ 500G",
        product_phrase="ΖΑΜΠΟΝ ΜΠΟΥΤΙ ΒΡΑΣΤΟ 500G",
        quantity=1.0,
        unit="piece"
    )
    assert res.best_match is not None
    assert res.best_match.sku == "18452"
    assert res.confidence.score == 0.96
    assert res.confidence.decision == MatchDecision.AUTO_ACCEPT
    assert any("Exact product description match" in r for r in res.confidence.reasons)


def test_fuzzy_matching_rapidfuzz(db_session):
    """
    'γαλοπουλα καπν' matches 'Γαλοπούλα Καπνιστή 1kg' via fuzzy match.
    Returns candidate with lower/medium confidence and needs_review.
    """
    data = setup_catalog(db_session)
    res = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_a"].id,
        line_number=1,
        original_text="2 γαλοπουλα καπν",
        product_phrase="γαλοπουλα καπν",
        quantity=2.0,
        unit="piece"
    )
    assert res.best_match is not None
    assert res.best_match.sku == "7843"
    assert any("Fuzzy description match" in r for r in res.confidence.reasons)
    assert res.confidence.decision in [MatchDecision.NEEDS_REVIEW, MatchDecision.UNRESOLVED]


def test_packaging_bonus_and_penalty(db_session):
    data = setup_catalog(db_session)

    # Compatible packaging: Prod1 has packaging 'case'
    res_compatible = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_a"].id,
        line_number=1,
        original_text="2 κουτες 18452",
        product_phrase="18452",
        quantity=2.0,
        unit="case",
        raw_unit="κουτες",
        unit_explicit=True
    )
    assert res_compatible.best_match.sku == "18452"
    # Base 0.98 + 0.03 packaging bonus = 1.0 (capped)
    assert any("Requested packaging/unit compatible" in r for r in res_compatible.confidence.reasons)

    # Incompatible packaging: Prod1 has no 'pallet' packaging
    res_incompatible = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_a"].id,
        line_number=1,
        original_text="5 παλετες 18452",
        product_phrase="18452",
        quantity=5.0,
        unit="pallet",
        raw_unit="παλετες",
        unit_explicit=True
    )
    assert res_incompatible.best_match.sku == "18452"
    # Base 0.98 - 0.15 = 0.83 -> needs_review
    assert res_incompatible.confidence.score == 0.83
    assert res_incompatible.confidence.decision == MatchDecision.NEEDS_REVIEW
    assert any("incompatible with product packaging" in r for r in res_incompatible.confidence.reasons)


def test_unknown_explicit_unit_safety(db_session):
    """
    Explicit unknown unit 'trays' must penalize and CANNOT be auto_accepted.
    """
    data = setup_catalog(db_session)
    res = MatchingEngine.match_line(
        db=db_session,
        company_id=data["company"].id,
        customer_id=data["customer_a"].id,
        line_number=1,
        original_text="5 trays 18452",
        product_phrase="18452",
        quantity=5.0,
        unit="unknown",
        raw_unit="trays",
        unit_explicit=True
    )
    assert res.best_match.sku == "18452"
    # 0.98 - 0.20 = 0.78 -> needs_review (never auto_accept)
    assert res.confidence.decision == MatchDecision.NEEDS_REVIEW
    assert res.confidence.score == 0.78
    assert any("Unknown explicit unit 'trays' requested" in r for r in res.confidence.reasons)


def test_company_isolation_between_different_companies(db_session):
    """
    Company 1 and Company 2 have identical SKU 'ISOLATED-1'.
    A match in Company 1 must never return Company 2's product.
    """
    comp1 = Company(name="Comp 1")
    comp2 = Company(name="Comp 2")
    db_session.add_all([comp1, comp2])
    db_session.flush()

    cust1 = Customer(company_id=comp1.id, customer_code="C1", customer_name="Cust 1")
    cust2 = Customer(company_id=comp2.id, customer_code="C2", customer_name="Cust 2")
    db_session.add_all([cust1, cust2])
    db_session.flush()

    p_comp1 = Product(company_id=comp1.id, sku="ISOLATED-1", description="Comp1 Item", active=True)
    p_comp2 = Product(company_id=comp2.id, sku="ISOLATED-1", description="Comp2 Item", active=True)
    db_session.add_all([p_comp1, p_comp2])
    db_session.commit()

    res1 = MatchingEngine.match_line(
        db=db_session,
        company_id=comp1.id,
        customer_id=cust1.id,
        line_number=1,
        original_text="ISOLATED-1",
        product_phrase="ISOLATED-1",
        quantity=1.0,
        unit="piece"
    )
    assert res1.best_match.product_id == p_comp1.id
    assert res1.best_match.description == "Comp1 Item"

    res2 = MatchingEngine.match_line(
        db=db_session,
        company_id=comp2.id,
        customer_id=cust2.id,
        line_number=1,
        original_text="ISOLATED-1",
        product_phrase="ISOLATED-1",
        quantity=1.0,
        unit="piece"
    )
    assert res2.best_match.product_id == p_comp2.id
    assert res2.best_match.description == "Comp2 Item"
