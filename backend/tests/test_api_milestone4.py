import io
import csv
import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend.app.models.company import Company
from backend.app.models.business_settings import CompanyBusinessSettings
from backend.app.models.customer import Customer
from backend.app.models.product import Product
from backend.app.models.memory import CustomerProductAlias


def setup_milestone4_api_data(db_session):
    company = Company(name="Olympus Provisions SA")
    db_session.add(company)
    db_session.flush()
    db_session.add(CompanyBusinessSettings(company_id=company.id, unitless_order_behavior="piece"))

    customer = Customer(
        company_id=company.id,
        customer_code="CUST-DELI",
        customer_name="Athens Deli Taverna",
        email="info@demo-deli.test"
    )
    db_session.add(customer)
    db_session.flush()

    prod_turkey = Product(
        company_id=company.id,
        sku="7843",
        description="Γαλοπούλα Καπνιστή 1kg",
        unit="piece",
        barcode="5201111111111",
        active=True
    )
    prod_salami = Product(
        company_id=company.id,
        sku="100",
        description="Σαλάμι Μπύρας 300g",
        unit="piece",
        barcode="5202222222222",
        active=True
    )
    db_session.add_all([prod_turkey, prod_salami])
    db_session.flush()

    # Create customer alias: "κοκκινο" -> 7843 with 8 confirmations (auto_accept)
    alias = CustomerProductAlias(
        customer_id=customer.id,
        product_id=prod_turkey.id,
        original_phrase="κοκκινο",
        normalized_phrase="κοκκινο",
        confirmed_count=8,
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


def test_e2e_milestone4_scenario_auto_accept_to_xlsx(client: TestClient, db_session):
    """
    Scenario 1:
    Create Company -> Customer -> Products -> Customer Alias
    -> Parse/Match & Persist Order: '10 κοκκινα'
    -> Line is auto_accepted
    -> Approve Order
    -> Create Export Profile (CUSTOMER, ITEM, QTY, WAREHOUSE='01')
    -> Export XLSX
    -> Read XLSX back with openpyxl
    -> Verify exact headers and values
    """
    data = setup_milestone4_api_data(db_session)
    comp_id = data["company"].id
    cust_id = data["customer"].id

    # 1. Create order from match directly via API
    create_payload = {
        "company_id": comp_id,
        "customer_id": cust_id,
        "text": "10 κοκκινα"
    }
    resp_create = client.post("/api/v1/orders/create-from-match", json=create_payload)
    assert resp_create.status_code == 201
    order_data = resp_create.json()
    order_id = order_data["id"]
    assert order_data["status"] == "pending_review"
    assert len(order_data["lines"]) == 1
    assert order_data["lines"][0]["status"] == "auto_accepted"
    assert order_data["lines"][0]["final_sku"] == "7843"

    # 2. Approve order
    resp_approve = client.post(f"/api/v1/orders/{order_id}/approve")
    assert resp_approve.status_code == 200
    approve_data = resp_approve.json()
    assert approve_data["status"] == "approved"
    assert approve_data["approved_lines"] == 1
    assert approve_data["pending_review_lines"] == 0

    # 3. Create Export Profile: CUSTOMER, ITEM, QTY, WAREHOUSE='01'
    profile_payload = {
        "company_id": comp_id,
        "name": "SoftOne ERP Excel",
        "format": "xlsx",
        "include_header": True,
        "mappings": [
            {"column_order": 1, "output_column_name": "CUSTOMER", "mapping_type": "source_field", "source_field": "customer.customer_code"},
            {"column_order": 2, "output_column_name": "ITEM", "mapping_type": "source_field", "source_field": "line.sku"},
            {"column_order": 3, "output_column_name": "QTY", "mapping_type": "source_field", "source_field": "line.quantity"},
            {"column_order": 4, "output_column_name": "WAREHOUSE", "mapping_type": "constant", "constant_value": "01"}
        ]
    }
    resp_prof = client.post("/api/v1/export-profiles", json=profile_payload)
    assert resp_prof.status_code == 201
    profile_id = resp_prof.json()["id"]

    # 4. Export XLSX
    resp_export = client.post(f"/api/v1/orders/{order_id}/export/{profile_id}")
    assert resp_export.status_code == 200
    assert "openxmlformats" in resp_export.headers["content-type"]
    assert "attachment; filename=" in resp_export.headers["content-disposition"]

    # 5. Read XLSX back with openpyxl and verify exact values
    wb = openpyxl.load_workbook(io.BytesIO(resp_export.content))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))

    assert len(rows) == 2
    # Headers
    assert rows[0] == ("CUSTOMER", "ITEM", "QTY", "WAREHOUSE")
    # Data row
    assert rows[1] == ("CUST-DELI", "7843", 10.0, "01")


def test_e2e_milestone4_scenario_needs_review_rejection_and_confirmation(client: TestClient, db_session):
    """
    Scenario 2:
    Order with needs_review phrase
    -> Approve -> Rejected (400)
    -> Operator confirms line
    -> Approve -> Success (200)
    -> Export CSV -> Verify delimiter and values
    """
    data = setup_milestone4_api_data(db_session)
    comp_id = data["company"].id
    cust_id = data["customer"].id

    # '1 καπνιστη' is fuzzy -> needs_review
    create_payload = {
        "company_id": comp_id,
        "customer_id": cust_id,
        "text": "1 καπνιστη"
    }
    resp_create = client.post("/api/v1/orders/create-from-match", json=create_payload)
    assert resp_create.status_code == 201
    order_data = resp_create.json()
    order_id = order_data["id"]
    line_id = order_data["lines"][0]["id"]
    assert order_data["lines"][0]["status"] == "needs_review"

    # 1. Approval attempt must be rejected
    resp_bad_approve = client.post(f"/api/v1/orders/{order_id}/approve")
    assert resp_bad_approve.status_code == 400
    assert "1 line(s) still require review" in resp_bad_approve.json()["detail"]

    # 2. Operator confirms the line
    confirm_payload = {
        "customer_id": cust_id,
        "product_id": data["prod_turkey"].id,
        "original_phrase": "καπνιστη"
    }
    resp_confirm = client.post(f"/api/v1/orders/{order_id}/lines/{line_id}/confirm", json=confirm_payload)
    assert resp_confirm.status_code == 200

    # 3. Now approval must succeed
    resp_approve = client.post(f"/api/v1/orders/{order_id}/approve")
    assert resp_approve.status_code == 200
    assert resp_approve.json()["status"] == "approved"

    # 4. Create CSV profile and export
    profile_payload = {
        "company_id": comp_id,
        "name": "Accounting CSV",
        "format": "csv",
        "delimiter": ";",
        "include_header": True,
        "mappings": [
            {"column_order": 1, "output_column_name": "ORDER_NO", "mapping_type": "source_field", "source_field": "order.order_number"},
            {"column_order": 2, "output_column_name": "CUSTOMER", "mapping_type": "source_field", "source_field": "customer.customer_code"},
            {"column_order": 3, "output_column_name": "ITEM", "mapping_type": "source_field", "source_field": "line.sku"},
            {"column_order": 4, "output_column_name": "QTY", "mapping_type": "source_field", "source_field": "line.quantity"}
        ]
    }
    resp_prof = client.post("/api/v1/export-profiles", json=profile_payload)
    profile_id = resp_prof.json()["id"]

    resp_export = client.post(f"/api/v1/orders/{order_id}/export/{profile_id}")
    assert resp_export.status_code == 200
    csv_rows = list(csv.reader(io.StringIO(resp_export.content.decode("utf-8-sig")), delimiter=";"))

    assert len(csv_rows) == 2
    assert csv_rows[0] == ["ORDER_NO", "CUSTOMER", "ITEM", "QTY"]
    assert csv_rows[1][1] == "CUST-DELI"
    assert csv_rows[1][2] == "7843"
    assert csv_rows[1][3] == "1.0"


def test_api_export_profile_crud_and_patch_line_values(client: TestClient, db_session):
    data = setup_milestone4_api_data(db_session)
    comp_id = data["company"].id
    cust_id = data["customer"].id

    # 1. Profile CRUD
    create_payload = {
        "company_id": comp_id,
        "name": "API Profile",
        "format": "json",
        "mappings": [
            {"column_order": 1, "output_column_name": "SKU", "mapping_type": "source_field", "source_field": "line.sku"}
        ]
    }
    resp = client.post("/api/v1/export-profiles", json=create_payload)
    assert resp.status_code == 201
    prof_id = resp.json()["id"]

    # GET list
    resp_list = client.get(f"/api/v1/export-profiles?company_id={comp_id}")
    assert resp_list.status_code == 200
    assert any(p["id"] == prof_id for p in resp_list.json())

    # GET single
    resp_get = client.get(f"/api/v1/export-profiles/{prof_id}")
    assert resp_get.status_code == 200
    assert resp_get.json()["name"] == "API Profile"

    # PUT update
    resp_put = client.put(f"/api/v1/export-profiles/{prof_id}", json={"name": "API Profile Updated"})
    assert resp_put.status_code == 200
    assert resp_put.json()["name"] == "API Profile Updated"

    # 2. Operator manual final values update via PATCH
    order_create = client.post("/api/v1/orders/create-from-match", json={
        "company_id": comp_id,
        "customer_id": cust_id,
        "text": "10 κοκκινα"
    }).json()
    order_id = order_create["id"]
    line_id = order_create["lines"][0]["id"]

    resp_invalid_unit = client.patch(
        f"/api/v1/orders/{order_id}/lines/{line_id}",
        json={"final_unit": "pallet"}
    )
    assert resp_invalid_unit.status_code == 400

    resp_kg = client.patch(
        f"/api/v1/orders/{order_id}/lines/{line_id}",
        json={"final_unit": "kg"}
    )
    assert resp_kg.status_code == 200

    resp_patch = client.patch(
        f"/api/v1/orders/{order_id}/lines/{line_id}",
        json={"final_quantity": 25.0, "final_unit": "piece"}
    )
    assert resp_patch.status_code == 200
    patched_line = resp_patch.json()
    assert patched_line["final_quantity"] == 25.0
    assert patched_line["final_unit"] == "piece"
    assert patched_line["requested_quantity"] == 10.0
    assert patched_line["requested_unit"] == "unknown"

    # Attempting to mutate product via PATCH has no effect on product
    orig_product_id = patched_line["matched_product_id"]
    resp_patch_prod = client.patch(
        f"/api/v1/orders/{order_id}/lines/{line_id}",
        json={"final_product_id": 9999, "final_quantity": 30.0}
    )
    assert resp_patch_prod.status_code == 200
    patched_line_prod = resp_patch_prod.json()
    assert patched_line_prod["matched_product_id"] == orig_product_id
    assert patched_line_prod["final_quantity"] == 30.0

    # Approve order
    resp_app = client.post(f"/api/v1/orders/{order_id}/approve")
    assert resp_app.status_code == 200
    assert resp_app.json()["status"] == "approved"

    # Modifying approved order lines via PATCH must return 400
    resp_patch_after_app = client.patch(
        f"/api/v1/orders/{order_id}/lines/{line_id}",
        json={"final_quantity": 40.0}
    )
    assert resp_patch_after_app.status_code == 400
    assert "lines cannot be modified" in resp_patch_after_app.json()["detail"]

    # Confirming line on approved order must return 400
    resp_confirm_after_app = client.post(
        f"/api/v1/orders/{order_id}/lines/{line_id}/confirm",
        json={"customer_id": cust_id, "product_id": orig_product_id, "original_phrase": "κοκκινα"}
    )
    assert resp_confirm_after_app.status_code == 400
    assert "lines cannot be modified" in resp_confirm_after_app.json()["detail"]

    # DELETE profile
    resp_del = client.delete(f"/api/v1/export-profiles/{prof_id}")
    assert resp_del.status_code == 204
