import os
import io
import pandas as pd
import pytest

from backend.app.models.company import Company
from backend.app.models.customer import Customer
from backend.app.models.product import Product, Packaging
from backend.app.services.master_data_service import MasterDataService


def test_excel_header_detection_and_heuristic_mapping(fixtures_dir):
    """Verify preview_excel extracts headers, preview rows and suggests probable mappings."""
    customers_file = os.path.join(fixtures_dir, "sample_customers.xlsx")
    with open(customers_file, "rb") as f:
        content = f.read()

    preview = MasterDataService.preview_excel(content, "customers")
    assert "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ" in preview.available_columns
    assert "ΕΠΩΝΥΜΙΑ_ΠΕΛΑΤΗ" in preview.available_columns
    assert len(preview.preview_rows) > 0
    assert preview.suggested_mapping.get("customer_code") == "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ"
    assert preview.suggested_mapping.get("customer_name") == "ΕΠΩΝΥΜΙΑ_ΠΕΛΑΤΗ"


def test_customer_import_success(db_session, fixtures_dir):
    """Verify successful customer import with custom column mapping."""
    comp = Company(name="Hellas Foods")
    db_session.add(comp)
    db_session.commit()

    customers_file = os.path.join(fixtures_dir, "sample_customers.xlsx")
    with open(customers_file, "rb") as f:
        content = f.read()

    mapping = {
        "customer_code": "ΚΩΔΙΚΟΣ_ΠΕΛΑΤΗ",
        "customer_name": "ΕΠΩΝΥΜΙΑ_ΠΕΛΑΤΗ",
        "email": "EMAIL",
        "phone": "ΤΗΛΕΦΩΝΟ",
        "active": "ΚΑΤΑΣΤΑΣΗ"
    }

    result = MasterDataService.import_customers(db_session, comp.id, content, mapping)
    assert result.total_rows == 4
    assert result.imported == 4
    assert result.errors == 0
    assert len(result.error_details) == 0

    # Verify rows in DB
    customers = db_session.query(Customer).filter_by(company_id=comp.id).all()
    assert len(customers) == 4
    codes = {c.customer_code for c in customers}
    assert "CUST-4531" in codes
    assert "CUST-1022" in codes


def test_customer_import_validation_and_duplicate_handling(db_session):
    """Verify invalid rows and duplicate codes are captured without silent failure."""
    comp = Company(name="Test Co")
    db_session.add(comp)
    db_session.commit()

    # Pre-insert one existing customer
    existing = Customer(company_id=comp.id, customer_code="EXISTING-01", customer_name="Old Customer")
    db_session.add(existing)
    db_session.commit()

    # Craft an excel with:
    # 1. Valid row
    # 2. Row with missing code
    # 3. Row with missing name
    # 4. Row with duplicate of existing in DB
    # 5. Row with duplicate inside sheet
    data = [
        {"KOD": "NEW-01", "ONOMA": "Valid Customer 1"},
        {"KOD": "", "ONOMA": "Missing Code Customer"},
        {"KOD": "NEW-02", "ONOMA": ""},
        {"KOD": "EXISTING-01", "ONOMA": "Duplicate DB Customer"},
        {"KOD": "NEW-01", "ONOMA": "Duplicate In-Sheet Customer"},
    ]
    df = pd.DataFrame(data)
    excel_buf = io.BytesIO()
    df.to_excel(excel_buf, index=False)
    content = excel_buf.getvalue()

    mapping = {
        "customer_code": "KOD",
        "customer_name": "ONOMA"
    }

    result = MasterDataService.import_customers(db_session, comp.id, content, mapping)
    assert result.total_rows == 5
    assert result.imported == 1
    assert result.errors == 4

    error_reasons = [err.reason for err in result.error_details]
    assert any("Customer code is missing" in r for r in error_reasons)
    assert any("Customer name is missing" in r for r in error_reasons)
    assert any("already exists for this company" in r for r in error_reasons)
    assert any("Duplicate customer code 'NEW-01' in upload sheet" in r for r in error_reasons)


def test_product_import_success(db_session, fixtures_dir):
    """Verify product import with custom column mapping."""
    comp = Company(name="Hellas Foods")
    db_session.add(comp)
    db_session.commit()

    products_file = os.path.join(fixtures_dir, "sample_products.xlsx")
    with open(products_file, "rb") as f:
        content = f.read()

    mapping = {
        "sku": "ΚΩΔΙΚΟΣ_ΕΙΔΟΥΣ",
        "description": "ΠΕΡΙΓΡΑΦΗ",
        "barcode": "BARCODE",
        "unit": "ΜΟΝΑΔΑ_ΜΕΤΡΗΣΗΣ",
        "active": "ΕΝΕΡΓΟ"
    }

    result = MasterDataService.import_products(db_session, comp.id, content, mapping)
    assert result.total_rows == 5
    assert result.imported == 5
    assert result.errors == 0

    products = db_session.query(Product).filter_by(company_id=comp.id).all()
    assert len(products) == 5
    skus = {p.sku for p in products}
    assert "SKU-7843" in skus
    assert "SKU-5001" in skus


def test_packaging_import_success_and_invalid_parent(db_session, fixtures_dir):
    """Verify packaging import and parent product SKU validation."""
    comp = Company(name="Hellas Foods")
    db_session.add(comp)
    db_session.commit()

    # Insert only 1 product (SKU-7843)
    p = Product(company_id=comp.id, sku="SKU-7843", description="Γαλοπούλα Καπνιστή 1kg")
    db_session.add(p)
    db_session.commit()

    packaging_file = os.path.join(fixtures_dir, "sample_packaging.xlsx")
    with open(packaging_file, "rb") as f:
        content = f.read()

    mapping = {
        "product_sku": "ΚΩΔ_ΕΙΔΟΥΣ",
        "package_type": "ΤΥΠΟΣ_ΣΥΣΚΕΥΑΣΙΑΣ",
        "pieces_per_case": "ΤΕΜ_ΚΙΒΩΤΙΟ",
        "weight": "ΒΑΡΟΣ_KG",
        "unit": "ΜΟΝΑΔΑ",
        "package_code": "ΚΩΔ_ΣΥΣΚΕΥΑΣΙΑΣ",
        "packaging_barcode": "BARCODE_ΚΙΒΩΤΙΟΥ"
    }

    result = MasterDataService.import_packaging(db_session, comp.id, content, mapping)
    # Out of 4 packaging rows in sample_packaging, only SKU-7843 exists in DB
    assert result.total_rows == 4
    assert result.imported == 1
    assert result.errors == 3  # other 3 SKUs do not exist yet!

    # Verify the imported packaging in DB
    packagings = db_session.query(Packaging).filter_by(product_id=p.id).all()
    assert len(packagings) == 1
    assert packagings[0].package_code == "BOX-7843-10"
    assert packagings[0].pieces_per_case == 10.0
