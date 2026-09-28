import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from backend.app.core.database import Base
from backend.app.models.company import Company
from backend.app.models.customer import Customer, CustomerContact
from backend.app.models.product import Product, ProductAlias, Packaging
from backend.app.models.memory import CustomerProductAlias, HumanCorrection
from backend.app.models.order import OrderSource, Order, OrderLine, MatchCandidate
from backend.app.models.export import ExportProfile, ExportFieldMapping


def test_all_models_registered_in_metadata():
    """Verify that all 14 entities are registered in SQLAlchemy metadata."""
    expected_tables = {
        'companies',
        'customers',
        'customer_contacts',
        'products',
        'product_aliases',
        'packagings',
        'customer_product_aliases',
        'human_corrections',
        'order_sources',
        'orders',
        'order_lines',
        'match_candidates',
        'export_profiles',
        'export_field_mappings'
    }
    actual_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(actual_tables), f"Missing tables: {expected_tables - actual_tables}"


def test_unique_product_sku_per_company(db_session):
    """
    Verify Product.sku is UNIQUE per company, but the SAME SKU is allowed across different companies.
    """
    comp1 = Company(name="Company A")
    comp2 = Company(name="Company B")
    db_session.add_all([comp1, comp2])
    db_session.commit()

    # Add SKU-100 to Company 1
    p1 = Product(company_id=comp1.id, sku="SKU-100", description="Product 1")
    db_session.add(p1)
    db_session.commit()

    # Same SKU-100 to Company 2 should SUCCEED (Company isolation)
    p2 = Product(company_id=comp2.id, sku="SKU-100", description="Product 2")
    db_session.add(p2)
    db_session.commit()
    assert p1.id != p2.id

    # Duplicate SKU-100 in Company 1 must FAIL with IntegrityError
    p_dup = Product(company_id=comp1.id, sku="SKU-100", description="Duplicate Product")
    db_session.add(p_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_customer_code_per_company(db_session):
    """
    Verify Customer.customer_code is UNIQUE per company, but allowed across different companies.
    """
    comp1 = Company(name="Company A")
    comp2 = Company(name="Company B")
    db_session.add_all([comp1, comp2])
    db_session.commit()

    c1 = Customer(company_id=comp1.id, customer_code="CUST-01", customer_name="Customer 1")
    c2 = Customer(company_id=comp2.id, customer_code="CUST-01", customer_name="Customer 1 Comp 2")
    db_session.add_all([c1, c2])
    db_session.commit()

    # Duplicate in Company 1 must FAIL
    c_dup = Customer(company_id=comp1.id, customer_code="CUST-01", customer_name="Customer Dup")
    db_session.add(c_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_product_global_alias(db_session):
    """Verify ProductAlias model and uniqueness."""
    comp = Company(name="Company Alpha")
    db_session.add(comp)
    db_session.commit()

    prod = Product(company_id=comp.id, sku="SKU-99", description="Special Cheese")
    db_session.add(prod)
    db_session.commit()

    alias1 = ProductAlias(
        company_id=comp.id,
        product_id=prod.id,
        original_phrase="τυρι κιτρινο",
        normalized_phrase="τυρι κιτρινο"
    )
    db_session.add(alias1)
    db_session.commit()

    # Duplicate global alias for the same product and company must fail
    alias_dup = ProductAlias(
        company_id=comp.id,
        product_id=prod.id,
        original_phrase="τυρι κιτρινο",
        normalized_phrase="τυρι κιτρινο"
    )
    db_session.add(alias_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_customer_product_alias_unique_constraint(db_session):
    """
    Verify CustomerProductAlias unique constraint on (customer_id, normalized_phrase).
    """
    comp = Company(name="Company Alpha")
    db_session.add(comp)
    db_session.commit()

    cust = Customer(company_id=comp.id, customer_code="C-1", customer_name="Test Customer")
    prod = Product(company_id=comp.id, sku="SKU-1", description="Gouda 1kg")
    db_session.add_all([cust, prod])
    db_session.commit()

    c_alias = CustomerProductAlias(
        customer_id=cust.id,
        product_id=prod.id,
        original_phrase="κοκκινο",
        normalized_phrase="κοκκινο",
        confirmed_count=1
    )
    db_session.add(c_alias)
    db_session.commit()

    # Same customer with same normalized phrase must fail
    c_alias_dup = CustomerProductAlias(
        customer_id=cust.id,
        product_id=prod.id,
        original_phrase="κόκκινο",
        normalized_phrase="κοκκινο",
        confirmed_count=2
    )
    db_session.add(c_alias_dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_order_line_json_confidence_reasons(db_session):
    """
    Verify OrderLine.confidence_reasons correctly persists and loads JSON list data.
    """
    comp = Company(name="Test Company")
    db_session.add(comp)
    db_session.commit()

    cust = Customer(company_id=comp.id, customer_code="C-1", customer_name="Cust")
    source = OrderSource(
        source_type="plain_text",
        raw_payload="3 κουτες ζαμπον",
        source_hash="dummy_hash_123",
        original_filename="order.txt",
        mime_type="text/plain"
    )
    db_session.add_all([cust, source])
    db_session.commit()

    order = Order(
        company_id=comp.id,
        customer_id=cust.id,
        order_source_id=source.id,
        order_number="ORD-2026-001",
        raw_input="3 κουτες ζαμπον"
    )
    db_session.add(order)
    db_session.commit()

    reasons = ["+ Customer alias exact match", "+ Confirmed 8 previous times", "+ Packaging matched"]
    line = OrderLine(
        order_id=order.id,
        line_number=1,
        original_text="3 κουτες ζαμπον",
        product_phrase="ζαμπον",
        requested_quantity=3,
        requested_unit="case",
        confidence_score=0.94,
        confidence_reasons=reasons
    )
    db_session.add(line)
    db_session.commit()

    # Query back
    saved_line = db_session.execute(select(OrderLine).where(OrderLine.id == line.id)).scalar_one()
    assert isinstance(saved_line.confidence_reasons, list)
    assert saved_line.confidence_reasons == reasons
    assert saved_line.confidence_score == 0.94
